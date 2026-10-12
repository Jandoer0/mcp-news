-- Индексы под горячие запросы: лента (фильтр по дате/источнику, сортировка),
-- живой опрос тегов/редактора (posts_tags), ротация (date ASC).
CREATE INDEX IF NOT EXISTS idx_posts_date_id ON posts (date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_posts_source_id ON posts (source_id);
CREATE INDEX IF NOT EXISTS idx_posts_tags_topic ON posts_tags (topic_id);
CREATE INDEX IF NOT EXISTS idx_posts_tags_post ON posts_tags (post_id);
CREATE INDEX IF NOT EXISTS idx_posts_text_source ON posts (source_id, text);
