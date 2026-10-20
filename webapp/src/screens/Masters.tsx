import { useStore } from '../App'
import { Avatar, Stars } from '../components/ui'
import { duration, rub } from '../format'
import { haptic, useBackButton, useMainButton } from '../tg'

export function Masters() {
  const { config, catalog, draft, setDraft, push, back } = useStore()
  const service = draft.service!
  const masters = catalog.masters.filter(m => m.offers[service.id])
  useBackButton(back)
  useMainButton(null, () => {})

  const choose = (masterId: number | null) => {
    haptic.tap()
    setDraft({ ...draft, masterId, day: undefined, slot: undefined })
    push({ name: 'time' })
  }

  return (
    <>
      <h1>{service.emoji} {service.name}</h1>
      <div className="muted">⏱ {duration(service.duration)}</div>
      <h2>{config.master_word}</h2>
      <div className="list">
        {masters.length > 1 && (
          <button className="card master" onClick={() => choose(null)}>
            <Avatar src="✨" />
            <div className="grow"><b>Любой свободный</b><div className="muted small">Покажем всё свободное время</div></div>
          </button>
        )}
        {masters.map(m => {
          const offer = m.offers[service.id]
          return (
            <button key={m.id} className="card master" onClick={() => choose(m.id)}>
              <Avatar src={m.photo} />
              <div className="grow">
                <b>{m.name}</b>
                <div className="muted small">{m.title}</div>
                <Stars rating={m.rating} reviews={m.reviews} />
                {m.bio && <div className="small">{m.bio}</div>}
              </div>
              <div className="price">{rub(offer.price ?? service.price)}
                {offer.duration && offer.duration !== service.duration && <div className="muted small">{duration(offer.duration)}</div>}
              </div>
            </button>
          )
        })}
      </div>
    </>
  )
}
