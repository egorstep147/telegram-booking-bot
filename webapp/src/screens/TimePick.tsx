import { useEffect, useState } from 'react'
import { useStore } from '../App'
import { api } from '../api'
import { DateStrip, Spinner } from '../components/ui'
import { dateLong, dayLong, time } from '../format'
import { haptic, inTelegram, openInvoice, useBackButton, useMainButton } from '../tg'
import type { Day, Slot } from '../types'

/** Выбор дня и времени. Для переноса (draft.reschedule) сразу переносим запись. */
export function TimePick() {
  const { config, catalog, draft, setDraft, push, back, reset, toast } = useStore()
  const service = draft.service!
  const [days, setDays] = useState<Day[] | null>(null)
  const [day, setDay] = useState(draft.day ?? '')
  const [slots, setSlots] = useState<Slot[] | null>(null)
  const [busy, setBusy] = useState(false)
  const master = catalog.masters.find(m => m.id === draft.masterId)

  useEffect(() => {
    api.days(service.id, draft.masterId ?? null).then(ds => {
      setDays(ds)
      if (!day) setDay(ds.find(d => d.free)?.date ?? ds[0].date) // первый день со свободным временем
    })
  }, [])
  useEffect(() => {
    if (!day) return
    setSlots(null)
    api.slots(service.id, day, draft.masterId ?? null).then(setSlots)
  }, [day])

  async function pick(slot: Slot) {
    haptic.tap()
    if (!draft.reschedule) {
      setDraft({ ...draft, day, slot })
      push({ name: 'confirm' })
      return
    }
    setBusy(true)
    try {
      const { booking, invoice } = await api.reschedule(draft.reschedule.id, slot.start)
      if (invoice && (await openInvoice(invoice)) !== 'paid') toast('Запись ждёт оплату — она в «Моих записях»')
      haptic.ok()
      reset({ name: 'done', booking, paid: false })
    } catch (e) {
      haptic.error()
      toast((e as Error).message)
      api.slots(service.id, day, draft.masterId ?? null).then(setSlots)
    } finally {
      setBusy(false)
    }
  }

  async function joinWaitlist() {
    if (!inTelegram) return toast('Откройте приложение из Telegram')
    try {
      await api.waitlist(service.id, draft.masterId ?? null, day)
      haptic.ok()
      toast('Готово! Напишем, если время освободится')
    } catch (e) { toast((e as Error).message) }
  }

  useBackButton(back)
  useMainButton(null, () => {})

  // Утро / день / вечер — так в длинном списке времени легче ориентироваться
  const groups = [['Утро', 0, 12], ['День', 12, 17], ['Вечер', 17, 24]] as const
  const hour = (s: Slot) => Number(s.time.slice(0, 2))

  return (
    <>
      <h1>{draft.reschedule ? 'Перенос записи' : 'Выберите время'}</h1>
      <div className="muted">{service.emoji} {service.name} · {master ? master.name : `любой ${config.master_word.toLowerCase()}`}</div>
      {draft.reschedule && <div className="note">Сейчас: {dayLong(draft.reschedule.start)}, {time(draft.reschedule.start)}</div>}
      {!days ? <Spinner /> : <DateStrip days={days} value={day} onChange={d => { haptic.tap(); setDay(d) }} />}
      {day && <h2>{dateLong(day)}</h2>}
      {slots === null ? <Spinner /> : slots.length === 0 ? (
        <div className="empty small-empty">
          <div>😔</div>
          На этот день свободного времени нет
          {config.waitlist && !draft.reschedule && (
            <button className="pill accent" onClick={joinWaitlist}>🔔 Сообщить, если освободится</button>
          )}
        </div>
      ) : groups.map(([title, from, to]) => {
        const part = slots.filter(s => hour(s) >= from && hour(s) < to)
        return part.length > 0 && (
          <div key={title}>
            <div className="group-title">{title}</div>
            <div className="slots">
              {part.map(s => (
                <button key={s.start} className={'slot' + (draft.slot?.start === s.start ? ' on' : '')} disabled={busy}
                  onClick={() => pick(s)}>{s.time}</button>
              ))}
            </div>
          </div>
        )
      })}
    </>
  )
}
