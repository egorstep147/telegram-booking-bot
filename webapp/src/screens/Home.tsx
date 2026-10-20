import { useState } from 'react'
import { useStore } from '../App'
import { duration, rub } from '../format'
import { haptic, inTelegram, useBackButton, useMainButton } from '../tg'

export function Home() {
  const { config, catalog, staff, push, setDraft } = useStore()
  const categories = [...new Set(catalog.services.map(s => s.category))]
  const [cat, setCat] = useState('')
  useBackButton(null)
  useMainButton(null, () => {})

  // «от 1 200 ₽»: у разных мастеров услуга может стоить по-разному
  const minPrice = (id: number) => Math.min(...catalog.masters
    .map(m => m.offers[id]).filter(Boolean).map(o => o.price ?? catalog.services.find(s => s.id === id)!.price))

  return (
    <>
      <header className="top">
        <div>
          <h1>{config.emoji} {config.name}</h1>
          {config.tagline && <div className="muted">{config.tagline}</div>}
          {config.address && <div className="muted small">📍 {config.address}</div>}
        </div>
      </header>
      {inTelegram && (
        <div className="actions">
          <button className="pill" onClick={() => push({ name: 'my' })}>📋 Мои записи</button>
          {staff && <button className="pill" onClick={() => push({ name: 'staff' })}>🗓 Кабинет</button>}
        </div>
      )}
      {categories.length > 1 && (
        <div className="chips">
          <button className={'chip' + (cat === '' ? ' on' : '')} onClick={() => setCat('')}>Все</button>
          {categories.map(c => (
            <button key={c} className={'chip' + (c === cat ? ' on' : '')} onClick={() => { haptic.tap(); setCat(c) }}>{c}</button>
          ))}
        </div>
      )}
      <div className="list">
        {catalog.services.filter(s => !cat || s.category === cat).map(s => (
          <button key={s.id} className="card service" onClick={() => { haptic.tap(); setDraft({ service: s }); push({ name: 'masters' }) }}>
            <div className="emoji">{s.emoji}</div>
            <div className="grow">
              <b>{s.name}</b>
              {s.description && <div className="muted small">{s.description}</div>}
              <div className="small">⏱ {duration(s.duration)}</div>
            </div>
            <div className="price">от {rub(minPrice(s.id))}</div>
          </button>
        ))}
      </div>
    </>
  )
}
