-- 阶段2审查修复：照片/定位尝试显式归属书籍与电子版本，避免把 photos.id 当 book_id。
ALTER TABLE photos ADD COLUMN book_id TEXT REFERENCES bookshelves(id) ON DELETE CASCADE;
ALTER TABLE photos ADD COLUMN edition_id TEXT REFERENCES editions(id) ON DELETE CASCADE;
ALTER TABLE location_attempts ADD COLUMN book_id TEXT REFERENCES bookshelves(id) ON DELETE CASCADE;
