import { useEffect, useMemo, useState } from 'react'
import { useStore } from '../App'
import { api } from '../api'
import { DateStrip, Spinner } from '../components/ui'
import { dateLong, rub, time, zonedIso } from '../format'
import { haptic, useBackButton, useMainButton } from '../tg'
import type { Booking, TimeOff } from '../types'

/** Кабинет мастера: расписание по дням, отметки «пришёл / не пришёл», выходные и перерывы. */
export function Staff() {
  const { config, staff, back, toast } = useStore()
  const [masterId, setMasterId] = useState<number | null>(staff?.masters[0]?.id ?? null)
  // Лента: неделя назад (отметить прошедшие визиты) и две вперёд
  const days = useMemo(() => Array.from({ length: 22 }, (_, i) => {
    const d = new Date(config.today + 'T12:00:00Z')
    d.setUTCDate(d.getUTCDate() + i - 7)
    return { date: d.toISOString().slice(0, 10), free: 1 }
  }), [config.today])
  const [day, setDay] = useState(config.today)
  const [data, setData] = useState<{ bookings: Booking[]; time_off: TimeOff[] } | null>(null)
  const [off, setOff] = useState({ from: '13:00', to: '14:00', reason: 'Перерыв' })

  const load = () => { if (masterId) api.staffSchedule(masterId, day).then(setData).catch(e => toast(e.message)) }
  useEffect(() => { setData(null); load() }, [masterId, day])
  useBackButton(back)
  useMainButton(null, () => {})

  async function setStatus(b: Booking, status: string) {
    try { await api.staffStatus(b.id, status); haptic.ok(); load() } catch (e) { toast((e as Error).message) }
  }

  async function addOff(allDay: boolean) {
    if (!masterId) return
    const [from, to] = allDay ? ['00:00', '23:59'] : [off.from, off.to]
    try {
      await api.addTimeOff({ master_id: masterId, starts_at: zonedIso(day, from), ends_at: zonedIso(day, to),
        reason: allDay ? 'Выходной' : off.reason })
      haptic.ok()
      load()
    } catch (e) { toast((e as Error).message) }
  }

  if (!staff) return <div className="empty"><div>🔒</div>Кабинет доступен только мастерам</div>
  const now = Date.now()
  const total = data?.bookings.filter(b => b.status !== 'cancelled').reduce((s, b) => s + b.price, 0) ?? 0

  return (
    <>
      <h1>🗓 Кабинет</h1>
      {staff.masters.length > 1 && (
        <div className="chips">
          {staff.masters.map(m => (
            <button key={m.id} className={'chip' + (m.id === masterId ? ' on' : '')} onClick={() => setMasterId(m.id)}>
              {m.photo} {m.name}</button>
          ))}
        </div>
      )}
      <DateStrip days={days} value={day} onChange={setDay} />
      <h2>{dateLong(day)}{data && ` · ${data.bookings.length} записей · ${rub(total)}`}</h2>
      {!data ? <Spinner /> : data.bookings.length === 0 ? <div className="note">Записей нет</div> : (
        <div className="list">
          {data.bookings.map(b => {
            const started = new Date(b.start).getTime() <= now
            return (
              <div key={b.id} className={'card booking' + (b.status === 'no_show' ? ' dim' : '')}>
                <div className="row">
                  <div className="timecol"><b>{time(b.start)}</b><span className="muted small">{time(b.end)}</span></div>
                  <div className="grow">
                    <b>{b.service.emoji} {b.service.name}</b>
                    <div>{b.name} · <a href={`tel:${b.phone}`}>{b.phone}</a></div>
                    {b.comment && <div className="muted small">💬 {b.comment}</div>}
                    <div className="muted small">{b.status_label} · {rub(b.price)}{b.paid ? ` · оплачено ${rub(b.paid)}` : ''}</div>
                  </div>
                </div>
                <div className="actions">
                  {started && ['confirmed', 'completed', 'no_show'].includes(b.status) && <>
                    <button className={'pill' + (b.status === 'completed' ? ' accent' : '')} onClick={() => setStatus(b, 'completed')}>✔️ Пришёл</button>
                    <button className={'pill' + (b.status === 'no_show' ? ' accent' : '')} onClick={() => setStatus(b, 'no_show')}>🚫 Не пришёл</button>
                  </>}
                  {!started && ['pending', 'confirmed'].includes(b.status) &&
                    <button className="pill" onClick={() => setStatus(b, 'cancelled')}>✖️ Отменить</button>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <h2>Выходные и перерывы</h2>
      {data?.time_off.map(t => (
        <div key={t.id} className="card row">
          <div className="grow">{time(t.start)}–{time(t.end)} {t.reason}</div>
          <button className="link" onClick={() => api.deleteTimeOff(t.id).then(() => load())}>Убрать</button>
        </div>
      ))}
      <div className="card offform">
        <input type="time" value={off.from} onChange={e => setOff({ ...off, from: e.target.value })} />
        <span>—</span>
        <input type="time" value={off.to} onChange={e => setOff({ ...off, to: e.target.value })} />
        <input value={off.reason} maxLength={100} onChange={e => setOff({ ...off, reason: e.target.value })} />
      </div>
      <div className="actions">
        <button className="pill" onClick={() => addOff(false)}>➕ Закрыть время</button>
        <button className="pill" onClick={() => addOff(true)}>🏖 Весь день выходной</button>
      </div>
      <div className="muted small">Закрытое время пропадёт из записи. Уже записанных клиентов отмените отдельно.</div>
      <div className="spacer" />
    </>
  )
}
