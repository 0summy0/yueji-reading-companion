-- 云服务接入：照片可由前端直传 WorkBuddy 云存储，这里记录云端对象路径。
ALTER TABLE photos ADD COLUMN cloud_path TEXT;
