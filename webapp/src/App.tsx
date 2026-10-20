import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'
import { FallbackButton, Spinner, Toast } from './components/ui'
import { setZone } from './format'
import { Confirm } from './screens/Confirm'
import { Done } from './screens/Done'
import { Home } from './screens/Home'
import { Masters } from './screens/Masters'
import { MyBookings } from './screens/MyBookings'
import { Staff } from './screens/Staff'
import { TimePick } from './screens/TimePick'
import { inTelegram } from './tg'
import type { Booking, Catalog, Config, Service, Slot, StaffMe } from './types'

export type Screen =
  | { name: 'home' }
  | { name: 'masters' }
  | { name: 'time' }
  | { name: 'confirm' }
  | { name: 'done'; booking: Booking; paid: boolean }
  | { name: 'my' }
  | { name: 'staff' }

/** Что клиент выбрал по шагам. reschedule — переносим существующую запись. */
export interface Draft {
  service?: Service
  masterId?: number | null // null — любой свободный
  day?: string
  slot?: Slot
  reschedule?: Booking
}

interface Store {
  config: Config
  catalog: Catalog
  staff: StaffMe | null
  draft: Draft
  setDraft: (d: Draft) => void
  push: (s: Screen) => void
  back: (() => void) | null
  reset: (s?: Screen) => void
  toast: (text: string) => void
}

const Ctx = createContext<Store>(null!)
export const useStore = () => useContext(Ctx)

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [staff, setStaff] = useState<StaffMe | null>(null)
  const [error, setError] = useState('')
  const [stack, setStack] = useState<Screen[]>([{ name: 'home' }])
  const [draft, setDraft] = useState<Draft>({})
  const [toastText, setToastText] = useState('')

  const toast = useCallback((text: string) => {
    setToastText(text)
    setTimeout(() => setToastText(t => (t === text ? '' : t)), 2800)
  }, [])

  useEffect(() => {
    Promise.all([api.config(), api.catalog()]).then(async ([c, cat]) => {
      setZone(c.timezone)
      document.title = c.name
      document.documentElement.style.setProperty('--accent', c.accent)
      setConfig(c)
      setCatalog(cat)
      if (inTelegram) api.staffMe().then(setStaff).catch(() => {}) // 403 — обычный клиент
      // Ссылки из бота: #staff, #booking/12 (перенос), #book/<услуга>/<мастер> («пора снова»)
      const [route, a, b] = location.hash.slice(1).split('/')
      if (route === 'staff') setStack([{ name: 'home' }, { name: 'staff' }])
      if (route === 'booking' && inTelegram) {
        const booking = (await api.mine()).find(x => x.id === Number(a))
        if (booking?.can_change) {
          setDraft({ service: cat.services.find(s => s.id === booking.service.id), masterId: booking.master.id, reschedule: booking })
          setStack([{ name: 'home' }, { name: 'my' }, { name: 'time' }])
        } else setStack([{ name: 'home' }, { name: 'my' }])
      }
      if (route === 'book') {
        const service = cat.services.find(s => s.id === Number(a))
        if (service) {
          setDraft({ service, masterId: b ? Number(b) : null })
          setStack([{ name: 'home' }, { name: 'masters' }, { name: 'time' }])
        }
      }
    }).catch(e => setError(e.message))
  }, [])

  if (error) return <div className="empty"><div>⚠️</div>{error}</div>
  if (!config || !catalog) return <Spinner />

  const screen = stack[stack.length - 1]
  const store: Store = {
    config, catalog, staff, draft, setDraft, toast,
    push: s => { setStack(st => [...st, s]); window.scrollTo(0, 0) },
    back: stack.length > 1 ? () => setStack(st => st.slice(0, -1)) : null,
    reset: (s = { name: 'home' }) => { setStack(s.name === 'home' ? [s] : [{ name: 'home' }, s]); setDraft({}) },
  }

  return (
    <Ctx.Provider value={store}>
      <div className="page">
        {screen.name === 'home' && <Home />}
        {screen.name === 'masters' && <Masters />}
        {screen.name === 'time' && <TimePick />}
        {screen.name === 'confirm' && <Confirm />}
        {screen.name === 'done' && <Done booking={screen.booking} paid={screen.paid} />}
        {screen.name === 'my' && <MyBookings />}
        {screen.name === 'staff' && <Staff />}
      </div>
      <FallbackButton />
      <Toast text={toastText} />
    </Ctx.Provider>
  )
}
