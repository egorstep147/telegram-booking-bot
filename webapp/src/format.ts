// Даты показываем в часовом поясе бизнеса (config.timezone), а не устройства:
// клиент в другом городе видит время так, как его ждёт салон

let zone = 'Europe/Moscow'
export const setZone = (tz: string) => { zone = tz }

const fmt = (iso: string, opts: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('ru-RU', { timeZone: zone, ...opts }).format(new Date(iso))

export const time = (iso: string) => fmt(iso, { hour: '2-digit', minute: '2-digit' })
export const dayLong = (iso: string) => fmt(iso, { weekday: 'long', day: 'numeric', month: 'long' })
export const dayShort = (iso: string) => fmt(iso, { day: 'numeric', month: 'short' })

/** Дата без времени («2026-11-03»): форматируем в UTC, иначе пояс +12 сдвинет её на сутки. */
export const dateLong = (date: string) => new Intl.DateTimeFormat('ru-RU',
  { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(date + 'T12:00:00Z'))

/** «2026-11-03» → части для ленты дат: число, день недели. Полдень — чтобы пояс не сдвинул дату. */
export function dayParts(date: string) {
  const d = new Date(date + 'T12:00:00Z')
  return {
    num: d.getUTCDate(),
    week: new Intl.DateTimeFormat('ru-RU', { weekday: 'short', timeZone: 'UTC' }).format(d),
    month: new Intl.DateTimeFormat('ru-RU', { month: 'short', timeZone: 'UTC' }).format(d),
    weekend: d.getUTCDay() === 0 || d.getUTCDay() === 6,
  }
}

export const rub = (n: number) => n.toLocaleString('ru-RU') + ' ₽'
export const duration = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} ч${m % 60 ? ` ${m % 60} мин` : ''}` : `${m} мин`)

/** «2026-11-03» + «14:30» в поясе бизнеса → ISO со смещением (нужен API для выходных мастера). */
export function zonedIso(date: string, hm: string): string {
  // Смещение пояса на эту дату: сравниваем, как одно и то же мгновение выглядит в UTC и в поясе
  const guess = new Date(`${date}T${hm}:00Z`)
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, hourCycle: 'h23', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).formatToParts(guess)
  const get = (t: string) => Number(parts.find(p => p.type === t)!.value)
  const asZone = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'))
  return new Date(guess.getTime() - (asZone - guess.getTime())).toISOString()
}
