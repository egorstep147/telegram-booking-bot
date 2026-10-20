import { useEffect, useState } from 'react'
import { useStore } from '../App'
import { api } from '../api'
import { Avatar, Spinner } from '../components/ui'
import { dayLong, rub, time } from '../format'
import { haptic, openInvoice, tg, useBackButton, useMainButton } from '../tg'
import type { Booking } from '../types'

function confirmDialog(text: string): Promise<boolean> {
  return new Promise(resolve => (tg?.showConfirm ? tg.showConfirm(text, resolve) : resolve(window.confirm(text))))
}

export function MyBookings() {
  const { config, catalog, setDraft, push, back, reset, toast } = useStore()
  const [list, setList] = useState<Booking[] | null>(null)
  const load = () => api.mine().then(setList).catch(e => toast(e.message))
  useEffect(() => { load() }, [])
  useBackButton(back ?? (() => reset()))
  useMainButton('Новая запись', () => reset())

  async function cancel(b: Booking) {
    if (!(await confirmDialog(`Отменить запись на ${dayLong(b.start)}, ${time(b.start)}?`))) return
    try { await api.cancel(b.id); haptic.ok(); toast('Запись отменена'); load() } catch (e) { toast((e as Error).message) }
  }

  function reschedule(b: Booking) {
    setDraft({ service: catalog.services.find(s => s.id === b.service.id), masterId: b.master.id, reschedule: b })
    push({ name: 'time' })
  }

  async function pay(b: Booking) {
    try {
      if ((await openInvoice((await api.payAgain(b.id)).invoice)) === 'paid') toast('✅ Оплачено')
      setTimeout(load, 1500) // подтверждение оплаты приходит боту чуть позже
    } catch (e) { toast((e as Error).message) }
  }

  if (list === null) return <Spinner />
  if (!list.length) return <div className="empty"><div>📋</div>Предстоящих записей нет</div>
  return (
    <>
      <h1>Мои записи</h1>
      {list.map(b => (
        <div key={b.id} className="card booking">
          <div className="row">
            <Avatar src={b.master.photo} size={44} />
            <div className="grow">
              <b>{dayLong(b.start)}, {time(b.start)}</b>
              <div>{b.service.emoji} {b.service.name} · {b.master.name}</div>
              <div className="muted small">{b.status_label} · {rub(b.price)}{b.address && ` · ${b.address}`}</div>
            </div>
          </div>
          <div className="actions">
            {b.status === 'pending' && <button className="pill accent" onClick={() => pay(b)}>💳 Оплатить {rub(b.prepay - b.paid)}</button>}
            {b.can_change ? <>
              <button className="pill" onClick={() => reschedule(b)}>🔁 Перенести</button>
              <button className="pill" onClick={() => cancel(b)}>✖️ Отменить</button>
            </> : <span className="muted small">Изменить можно не позже чем за {config.cancel_before_hours} ч — позвоните{config.phone && ` ${config.phone}`}</span>}
          </div>
        </div>
      ))}
    </>
  )
}
