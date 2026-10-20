// Типы ответов API (src/booking/api/routes.py)

export interface Config {
  name: string
  tagline: string
  emoji: string
  accent: string
  address: string
  phone: string
  master_word: string
  cancel_before_hours: number
  waitlist: boolean
  max_days_ahead: number
  timezone: string
  prepay: { mode: 'none' | 'deposit' | 'full'; deposit: number; hold_minutes: number }
  today: string
}

export interface Service {
  id: number
  name: string
  category: string
  description: string
  emoji: string
  duration: number
  price: number
}

export interface Master {
  id: number
  name: string
  title: string
  bio: string
  photo: string
  branch: string
  address: string
  rating: number | null
  reviews: number
  offers: Record<string, { price: number | null; duration: number | null }>
}

export interface Catalog { services: Service[]; masters: Master[] }
export interface Day { date: string; free: number }
export interface Slot { start: string; time: string; masters: number[] }

export interface Booking {
  id: number
  status: 'pending' | 'confirmed' | 'completed' | 'no_show' | 'cancelled'
  status_label: string
  start: string
  end: string
  service: { id: number; name: string; emoji: string }
  master: { id: number; name: string; photo: string }
  address: string
  price: number
  prepay: number
  paid: number
  can_change: boolean
  name: string
  phone: string
  comment: string
}

export interface TimeOff { id: number; start: string; end: string; reason: string }
export interface StaffMe { admin: boolean; masters: { id: number; name: string; photo: string }[] }
