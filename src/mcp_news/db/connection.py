"""Подключение к SQLite и механизм миграций.

Одна таблица ``sources`` описывает все подписки:
  * kind = "telegram"  -> канал Telegram, забираем через t.me/s/<name>
  * kind = "rss"       -> любая RSS/RSSHub лента, забираем по полю url

Таблица ``posts`` содержит кешированные посты по каждой подписке.
Таблицы ``topics`` / ``posts_tags`` / ``topic_exclusions`` обслуживают
«Мои темы».
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "telegram_cache.db")
# Максимальный размер базы в байтах (по умолчанию 100 МБ).
MAX_DB_BYTES = int(os.environ.get("MAX_DB_BYTES", str(100 * 1024 * 1024)))
# Каталог для БД создаём заранее, чтобы volume-монтирование не падало.
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Включаем внешние ключи: схема описывает ON DELETE CASCADE, поэтому
    # удаление источника/темы/поста корректно тянет за собой зависимости.
    conn.execute("PRAGMA foreign_keys=ON")
    # Ждём блокировку вместо мгновенного "database is locked": сервер
    # многопоточный (веб + планировщик + пул агента + редактор).
    conn.execute("PRAGMA busy_timeout=5000")
    # WAL: параллельное чтение (веб) не блокируется записью (лента/агент).
    # Размер файла для ротации меряем после checkpoint TRUNCATE (см. ниже),
    # поэтому точность лимита сохраняется.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY, "
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {int(r["version"]) for r in rows}


def _discover_migrations() -> list[tuple[int, Path]]:
    found = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        stem = p.stem  # NNNN_name
        num = stem.split("_", 1)[0]
        if num.isdigit():
            found.append((int(num), p))
    return sorted(found, key=lambda x: x[0])


def run_migrations(conn: sqlite3.Connection | None = None) -> None:
    """Применить все ещё не применённые миграции из db/migrations."""
    owned = conn is None
    conn = conn or get_conn()
    try:
        _ensure_version_table(conn)
        applied = _applied_versions(conn)
        for version, path in _discover_migrations():
            if version in applied:
                continue
            logger.info("Применяется миграция %s", path.name)
            with open(path, encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
    finally:
        if owned:
            conn.close()


def init_db() -> None:
    """Инициализировать БД (создать таблицы, если их нет)."""
    run_migrations()


# --------------------------------------------------------------------------- #
# Ротация базы по лимиту размера
# --------------------------------------------------------------------------- #
def _get_db_size() -> int:
    """Физический размер базы на диске (main + wal после checkpoint).

    WAL-режим держит данные в ``-wal``; перед замером выполняем
    ``wal_checkpoint(TRUNCATE)``, чтобы размер файла отражал реальные
    данные и лимит ротации оставался точным.
    """
    try:
        conn = get_conn()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception:
        pass
    try:
        return os.path.getsize(DB_PATH)
    except Exception:
        return 0


def rotate_if_needed() -> int:
    """Удалить самые старые посты, если база превысила MAX_DB_BYTES.

    Вызывается автоматически после save_posts и при старте сервера.
    Удаляются только посты (старые по полю date, затем id) — подписки
    (источники) не трогаются. После каждой пачки выполняется VACUUM,
    чтобы физически освободить место на диске. Цикл повторяется, пока
    размер базы (физический файл) не упадёт ниже 90% лимита (с запасом).

    Возвращает количество удалённых постов.
    """
    try:
        target_size = int(MAX_DB_BYTES * 0.9)
        deleted_total = 0
        conn = get_conn()
        for _ in range(50):
            current_size = _get_db_size()
            if current_size <= target_size:
                break
            total_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            if total_posts == 0:
                break
            batch = max(1, int(total_posts * 0.10))
            batch = min(batch, total_posts)
            conn.execute(
                """DELETE FROM posts WHERE id IN (
                       SELECT id FROM posts ORDER BY date ASC, id ASC LIMIT ?
                   )""",
                (batch,),
            )
            conn.commit()
            conn.execute("VACUUM")
            conn.commit()
            deleted_total += batch
        conn.close()
        if deleted_total:
            logger.info(
                "Ротация БД: удалено %d постов (лимит %d байт)",
                deleted_total, MAX_DB_BYTES,
            )
        return deleted_total
    except Exception as e:
        logger.error("Ошибка ротации БД: %s", e)
        return 0
