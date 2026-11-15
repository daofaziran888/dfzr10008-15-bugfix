/** 统一请求封装：拼后端地址、带操作人身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export interface JsonResult<T = unknown> {
  ok: boolean
  message: string
  code?: string | null
  entry?: T
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const session = useSessionStore()
  // 身份头只接受 latin-1，中文值按百分号编码，后端 security 层解码。
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  headers.set('X-Operator', encodeURIComponent(session.operator))
  headers.set('X-Operator-Unit', encodeURIComponent(session.operatorUnit))
  return fetch(url, { ...init, headers }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 动作/表单类 POST、PUT：后端业务拒绝时 HTTP 仍是 200，按 body.ok 抛业务消息。 */
export async function postJson<T = unknown>(
  path: string,
  body: unknown,
  method: 'POST' | 'PUT' = 'POST',
): Promise<JsonResult<T>> {
  const response = await request(path, { method, body: JSON.stringify(body) })
  const payload = (await response.json()) as JsonResult<T>
  if (!response.ok) {
    throw new Error(payload.message || `接口返回 ${response.status}，操作未生效`)
  }
  return payload
}
