import { tg } from './tg'
import type { Booking, Catalog, Config, Day, Slot, StaffMe, TimeOff } from './types'

// Каждый запрос несёт initData — подпись Telegram, по ней сервер узнаёт пользователя
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: 'tma ' + (tg?.initData ?? '') },
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = data.detail
    throw Object.assign(new Error(typeof d === 'string' ? d : Array.isArray(d) ? 'Проверьте заполнение полей' : r.statusText),
      { status: r.status })
  }
  return data as T
}

const send = <T>(path: string, body?: unknown, method = 'POST') =>
  request<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })
const q = (params: Record<string, string | number | null | undefined>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))

export interface BookingIn {
  service_id: number
  master_id: number | null
  start: string
  name: string
  phone: string
  comment: string
}

export type Created = { booking: Booking; invoice?: string }

export const api = {
  config: () => request<Config>('/api/config'),
  catalog: () => request<Catalog>('/api/catalog'),
  days: (service_id: number, master_id: number | null) => request<Day[]>('/api/days?' + q({ service_id, master_id })),
  slots: (service_id: number, day: string, master_id: number | null) =>
    request<Slot[]>('/api/slots?' + q({ service_id, day, master_id })),
  book: (body: BookingIn) => send<Created>('/api/bookings', body),
  mine: () => request<Booking[]>('/api/bookings'),
  cancel: (id: number) => send<Booking>(`/api/bookings/${id}/cancel`),
  reschedule: (id: number, start: string) => send<Created>(`/api/bookings/${id}/reschedule`, { start }),
  payAgain: (id: number) => send<{ invoice: string }>(`/api/bookings/${id}/invoice`),
  waitlist: (service_id: number, master_id: number | null, day: string) =>
    send<{ ok: boolean }>('/api/waitlist', { service_id, master_id, day }),
  staffMe: () => request<StaffMe>('/api/staff/me'),
  staffSchedule: (master_id: number, day: string) =>
    request<{ bookings: Booking[]; time_off: TimeOff[] }>('/api/staff/schedule?' + q({ master_id, day })),
  staffStatus: (id: number, status: string) => send<Booking>(`/api/staff/bookings/${id}/status`, { status }),
  addTimeOff: (body: { master_id: number; starts_at: string; ends_at: string; reason: string }) =>
    send<{ id: number }>('/api/staff/time-off', body),
  deleteTimeOff: (id: number) => send<{ ok: boolean }>(`/api/staff/time-off/${id}`, undefined, 'DELETE'),
}
