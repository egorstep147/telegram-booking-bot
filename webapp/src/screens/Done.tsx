import { useStore } from '../App'
import { dayLong, time } from '../format'
import { useBackButton, useMainButton } from '../tg'
import type { Booking } from '../types'

export function Done({ booking, paid }: { booking: Booking; paid: boolean }) {
  const { reset } = useStore()
  useBackButton(null)
  useMainButton('Готово', () => reset())
  const waiting = booking.status === 'pending' && !paid
  return (
    <div className="empty">
      <div>{waiting ? '⏳' : '🎉'}</div>
      <h1>{waiting ? 'Ждём оплату' : 'Вы записаны!'}</h1>
      <p>{booking.service.emoji} {booking.service.name}<br />{dayLong(booking.start)}, <b>{time(booking.start)}</b><br />
        {booking.master.photo} {booking.master.name}</p>
      <p className="muted">Подтверждение и напоминания придут в чат с ботом.</p>
      <button className="pill" onClick={() => reset({ name: 'my' })}>📋 Мои записи</button>
    </div>
  )
}
