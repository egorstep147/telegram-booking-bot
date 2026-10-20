import { useEffect, useRef, useState } from 'react'
import { dayParts } from '../format'
import type { Day } from '../types'

/** Фото мастера: URL — картинка, иначе эмодзи в кружке. */
export function Avatar({ src, size = 52 }: { src: string; size?: number }) {
  return src.startsWith('http') || src.startsWith('/')
    ? <img className="avatar" src={src} alt="" style={{ width: size, height: size }} />
    : <div className="avatar" style={{ width: size, height: size, fontSize: size * 0.55 }}>{src || '👤'}</div>
}

export function Stars({ rating, reviews }: { rating: number | null; reviews: number }) {
  return rating ? <span className="stars">★ {rating.toFixed(1)} <span className="muted">({reviews})</span></span>
    : <span className="muted small">нет отзывов</span>
}

/** Лента дат: дни без свободного времени — бледные, но нажимаются (можно встать в лист ожидания). */
export function DateStrip({ days, value, onChange }: { days: Day[]; value: string; onChange: (d: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  // Выбранный день — в зоне видимости (в кабинете лента начинается неделей раньше)
  useEffect(() => {
    ref.current?.querySelector('.on')?.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [value, days.length])
  return (
    <div className="dates" ref={ref}>
      {days.map(d => {
        const p = dayParts(d.date)
        return (
          <button key={d.date} className={'date' + (d.date === value ? ' on' : '') + (d.free ? '' : ' none') + (p.weekend ? ' weekend' : '')}
            onClick={() => onChange(d.date)}>
            <small>{p.week}</small><b>{p.num}</b><small>{p.month}</small>
          </button>
        )
      })}
    </div>
  )
}

export function Toast({ text }: { text: string }) {
  return text ? <div className="toast">{text}</div> : null
}

export function Spinner() {
  return <div className="empty"><div className="spinner" /></div>
}

/** Нижняя кнопка для браузера (в Telegram — нативная MainButton, см. useMainButton в tg.ts). */
export function FallbackButton() {
  const [state, setState] = useState<{ text: string | null; disabled?: boolean; onClick: () => void } | null>(null)
  useEffect(() => {
    const on = (e: Event) => setState((e as CustomEvent).detail)
    window.addEventListener('fallback-button', on)
    return () => window.removeEventListener('fallback-button', on)
  }, [])
  if (!state?.text) return null
  return <button className="fallback-btn" disabled={state.disabled} onClick={state.onClick}>{state.text}</button>
}
