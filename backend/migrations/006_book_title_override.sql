-- 允许用户修改书架显示书名，同时保留导入作品元数据与原文哈希不变。
ALTER TABLE bookshelves ADD COLUMN title_override TEXT;
