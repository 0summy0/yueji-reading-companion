import type { CloudSession } from '@tencent-ai/workbuddy-cloud-sdk';

import { cloud } from './config';

/** 统一错误消息提取：SDK 返回 { data, error }，error 可能是对象或字符串。 */
export function cloudErrorMessage(error: unknown, fallback = '云服务请求失败'): string {
  if (!error) return fallback;
  if (typeof error === 'string') return error;
  const candidate = error as { message?: string; error?: { message?: string } };
  return candidate.error?.message || candidate.message || fallback;
}

// ---------- Auth（邮箱 OTP） ----------

export async function getCloudSession(): Promise<CloudSession | null> {
  const { data, error } = await cloud.auth.getSession();
  if (error) throw new Error(cloudErrorMessage(error, '读取云端会话失败'));
  return data;
}

export async function sendEmailCode(email: string): Promise<{ verificationId: string; isExistingUser: boolean }> {
  const { data, error } = await cloud.auth.sendOtp({ email });
  if (error || !data) throw new Error(cloudErrorMessage(error, '验证码发送失败'));
  return { verificationId: data.verificationId, isExistingUser: data.isExistingUser };
}

export async function verifyEmailCode(input: {
  email: string;
  verificationId: string;
  isExistingUser: boolean;
  token: string;
}): Promise<CloudSession> {
  const { data, error } = await cloud.auth.verifyOtp({
    email: input.email,
    verificationId: input.verificationId,
    isExistingUser: input.isExistingUser,
    token: input.token,
  });
  if (error || !data) throw new Error(cloudErrorMessage(error, '验证码校验失败'));
  return data;
}

export async function signOutCloud(): Promise<void> {
  const { error } = await cloud.auth.signOut();
  if (error) throw new Error(cloudErrorMessage(error, '退出云端登录失败'));
}

// ---------- LLM（免密钥问答） ----------

export interface CloudModelInfo {
  id: string;
  label: string;
}

export async function listCloudModels(): Promise<CloudModelInfo[]> {
  const models = await cloud.llm.models.list();
  return models
    .filter((item) => item.disabled !== true)
    .map((item) => ({ id: item.id, label: item.name ?? item.id }));
}

// ---------- Storage（云相册） ----------

/** 前端去 EXIF：重绘到 canvas 再导出 JPEG，与后端清洗等效，且能控制上传体积。 */
export async function sanitizePhotoInBrowser(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const maxDim = 1600;
  const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext('2d');
  if (!context) throw new Error('当前浏览器无法处理照片');
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.88));
  if (!blob) throw new Error('照片处理失败，请换一张试试');
  return blob;
}

export async function uploadPhotoToCloud(uid: string, blob: Blob): Promise<{ path: string; signedUrl: string }> {
  const path = cloud.storage.userPath(uid, `photos/${crypto.randomUUID()}.jpg`);
  const uploaded = await cloud.storage.upload(path, blob, { contentType: 'image/jpeg', upsert: false });
  if (uploaded.error || !uploaded.data) throw new Error(cloudErrorMessage(uploaded.error, '照片上传云端失败'));
  const signed = await cloud.storage.createSignedUrl(uploaded.data.path, 3600);
  if (signed.error || !signed.data) throw new Error(cloudErrorMessage(signed.error, '照片签名失败'));
  return { path: uploaded.data.path, signedUrl: signed.data.signedUrl };
}

export async function listCloudPhotos(uid: string): Promise<string[]> {
  const attempt = () => cloud.storage.list(`users/${uid}/photos`, { limit: 100 });
  let result = await attempt();
  if (result.error) {
    // 登录刚完成时存储会话可能尚未附加；短暂等待后重试一次。
    await new Promise((resolve) => setTimeout(resolve, 1500));
    result = await attempt();
  }
  const { data, error } = result;
  if (error) throw new Error(cloudErrorMessage(error, '读取云相册失败'));
  return (data ?? []).map((item) => item.name).filter((name) => Boolean(name));
}

export async function createPhotoSignedUrl(path: string): Promise<string> {
  const { data, error } = await cloud.storage.createSignedUrl(path, 600);
  if (error || !data) throw new Error(cloudErrorMessage(error, '照片链接生成失败'));
  return data.signedUrl;
}

/** 云存储自检：上传小探针 → 签名下载 → 比对内容 → 删除，验证整条链路真实可用。 */
export async function probeCloudStorage(uid: string): Promise<void> {
  const probePath = cloud.storage.userPath(uid, `probe/${crypto.randomUUID()}.txt`);
  const content = `yueji-probe-${Date.now()}`;
  const uploaded = await cloud.storage.upload(probePath, new Blob([content], { type: 'text/plain' }), { contentType: 'text/plain' });
  if (uploaded.error) throw new Error(cloudErrorMessage(uploaded.error, '自检上传失败'));
  const signed = await cloud.storage.createSignedUrl(probePath, 300);
  if (signed.error || !signed.data) throw new Error(cloudErrorMessage(signed.error, '自检签名失败'));
  const response = await fetch(signed.data.signedUrl);
  if (!response.ok) throw new Error('自检下载失败');
  const text = await response.text();
  if (text !== content) throw new Error('自检内容不一致');
  await cloud.storage.remove([probePath]);
}

// ---------- Database（云备份） ----------

export interface CloudBackupMeta {
  id: number;
  label: string;
  created_at: string;
}

export interface CloudBackupRow extends CloudBackupMeta {
  payload: unknown;
}

function unwrap<T>(result: { data: T | null; error: unknown }, fallback: string): T {
  if (result.error) throw new Error(cloudErrorMessage(result.error, fallback));
  return result.data as T;
}

export async function listBackups(): Promise<CloudBackupMeta[]> {
  const result = await cloud.database
    .from('backups')
    .select('id, label, created_at')
    .order('created_at', { ascending: false })
    .limit(50);
  return unwrap(result as { data: CloudBackupMeta[] | null; error: unknown }, '读取云备份列表失败') ?? [];
}

export async function createBackup(label: string, payload: unknown, ownerName: string | null): Promise<CloudBackupMeta> {
  const result = await cloud.database
    .from('backups')
    .insert({ label, payload, owner_name: ownerName } as never)
    .select('id, label, created_at');
  const rows = unwrap(result as { data: CloudBackupMeta[] | null; error: unknown }, '备份写入云端失败') ?? [];
  if (!rows.length) throw new Error('备份写入被云端拒绝，请重新登录后再试');
  return rows[0];
}

export async function getBackup(id: number): Promise<CloudBackupRow> {
  const result = await cloud.database.from('backups').select('*').eq('id', id).single();
  return unwrap(result as { data: CloudBackupRow | null; error: unknown }, '读取备份内容失败');
}

export async function deleteBackup(id: number): Promise<void> {
  const result = await cloud.database.from('backups').delete().eq('id', id).select('id');
  const rows = unwrap(result as { data: { id: number }[] | null; error: unknown }, '删除备份失败') ?? [];
  if (!rows.length) throw new Error('备份不存在或不属于你');
}
