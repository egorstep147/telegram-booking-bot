import { useState } from 'react'
import { useStore } from '../App'
import { api } from '../api'
import { Avatar } from '../components/ui'
import { dayLong, duration, rub, time } from '../format'
import { haptic, inTelegram, openInvoice, requestPhone, tg, useBackButton, useMainButton } from '../tg'

// Имя и телефон запоминаем в браузере Telegram: при следующей записи не вводить заново
const saved = (() => { try { return JSON.parse(localStorage.getItem('contact') || '{}') } catch { return {} } })()

export function Confirm() {
  const { config, catalog, draft, back, reset, toast } = useStore()
  const service = draft.service!, slot = draft.slot!
  // «Любой мастер»: показываем первого из свободных, сервер выберет наименее загруженного
  const master = catalog.masters.find(m => m.id === (draft.masterId ?? slot.masters[0]))!
  const offer = master.offers[service.id]
  const price = offer.price ?? service.price
  const prepay = config.prepay.mode === 'full' ? price : config.prepay.mode === 'deposit' ? Math.min(config.prepay.deposit, price) : 0
  const [name, setName] = useState<string>(saved.name ?? tg?.initDataUnsafe.user?.first_name ?? '')
  const [phone, setPhone] = useState<string>(saved.phone ?? '')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!inTelegram) return toast('Откройте приложение из Telegram, чтобы записаться')
    if (!name.trim() || !phone.trim()) return toast('Укажите имя и телефон')
    setBusy(true)
    try {
      const { booking, invoice } = await api.book({ service_id: service.id, master_id: draft.masterId ?? null,
        start: slot.start, name, phone, comment })
      try { localStorage.setItem('contact', JSON.stringify({ name, phone })) } catch { /* приватный режим */ }
      let paid = false
      if (invoice) {
        paid = (await openInvoice(invoice)) === 'paid'
        if (!paid) toast(`Оплатите в течение ${config.prepay.hold_minutes} мин — запись в «Моих записях»`)
      }
      haptic.ok()
      reset({ name: 'done', booking, paid })
    } catch (e) {
      haptic.error()
      toast((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useBackButton(back)
  useMainButton(prepay ? `Записаться и оплатить ${rub(prepay)}` : 'Записаться', submit, { loading: busy })

  return (
    <>
      <h1>Подтверждение</h1>
      <div className="card summary">
        <div className="row"><span className="emoji">{service.emoji}</span>
          <div className="grow"><b>{service.name}</b><div className="muted small">{duration(offer.duration ?? service.duration)}</div></div>
          <b>{rub(price)}</b></div>
        <div className="row"><Avatar src={master.photo} size={36} />
          <div className="grow">{draft.masterId == null ? <>Любой свободный <span className="muted">(например, {master.name})</span></> : master.name}</div></div>
        <div className="row">📅 <div className="grow">{dayLong(slot.start)}, <b>{time(slot.start)}</b></div></div>
        {master.address && <div className="row">📍 <div className="grow">{master.address}</div></div>}
      </div>
      {prepay > 0 && (
        <div className="note">💳 Предоплата {rub(prepay)} — {config.prepay.mode === 'full' ? 'полная оплата онлайн' : 'остаток на месте'}.
          Время держим {config.prepay.hold_minutes} минут.</div>
      )}
      <h2>Ваши данные</h2>
      <label className="field"><span>Имя</span>
        <input value={name} maxLength={60} onChange={e => setName(e.target.value)} autoComplete="given-name" />
      </label>
      <label className="field"><span>Телефон</span>
        <input type="tel" value={phone} placeholder="+7 900 123-45-67" onChange={e => setPhone(e.target.value)} autoComplete="tel" />
      </label>
      {tg?.requestContact && (
        <button className="link" onClick={async () => { const p = await requestPhone(); if (p) setPhone(p) }}>📱 Взять номер из Telegram</button>
      )}
      <label className="field"><span>Комментарий</span>
        <textarea rows={2} maxLength={300} value={comment} onChange={e => setComment(e.target.value)} placeholder="Пожелания мастеру" />
      </label>
      <div className="muted small">Отменить или перенести можно не позже чем за {config.cancel_before_hours} ч.</div>
    </>
  )
}
