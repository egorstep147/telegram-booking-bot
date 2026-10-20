import { useEffect, useRef } from 'react'
import type { WebApp } from 'telegram-web-app'

// Telegram.WebApp есть, только если страницу открыл Telegram. В браузере — undefined: витрину смотреть
// можно, а заказывать нельзя (сервер не узнает пользователя)
export const tg: WebApp | undefined = window.Telegram?.WebApp?.initData ? window.Telegram.WebApp : undefined
export const inTelegram = !!tg

export const haptic = {
  tap: () => tg?.HapticFeedback.selectionChanged(),
  ok: () => tg?.HapticFeedback.notificationOccurred('success'),
  error: () => tg?.HapticFeedback.notificationOccurred('error'),
}

/** Нижняя большая кнопка. В Telegram — нативная MainButton, в браузере её рисует <FallbackButton>. */
export function useMainButton(text: string | null, onClick: () => void, opts: { loading?: boolean; disabled?: boolean } = {}) {
  // Обработчик кладём в ref: подписываемся один раз, а вызываем всегда свежую функцию
  const handler = useRef(onClick)
  handler.current = onClick
  useEffect(() => {
    if (!tg) return
    const fn = () => handler.current()
    tg.MainButton.onClick(fn)
    return () => { tg!.MainButton.offClick(fn) }
  }, [])
  useEffect(() => {
    if (!tg) {
      window.dispatchEvent(new CustomEvent('fallback-button', { detail: { text, disabled: opts.disabled, onClick: () => handler.current() } }))
      return
    }
    if (!text) { tg.MainButton.hide(); return }
    tg.MainButton.setParams({ text, is_visible: true, is_active: !opts.disabled })
    if (opts.loading) tg.MainButton.showProgress(); else tg.MainButton.hideProgress()
  }, [text, opts.loading, opts.disabled])
}

/** Кнопка «Назад» в шапке Telegram. */
export function useBackButton(onBack: (() => void) | null) {
  const handler = useRef(onBack)
  handler.current = onBack
  useEffect(() => {
    if (!tg) return
    if (!onBack) { tg.BackButton.hide(); return }
    const fn = () => handler.current?.()
    tg.BackButton.onClick(fn)
    tg.BackButton.show()
    return () => { tg!.BackButton.offClick(fn) }
  }, [!onBack])
}

/** Открыть форму оплаты поверх приложения. Результат: paid | cancelled | failed | pending. */
export function openInvoice(link: string): Promise<string> {
  return new Promise(resolve => (tg ? tg.openInvoice(link, resolve) : resolve('failed')))
}

/** Попросить у пользователя номер телефона из его аккаунта Telegram. */
export function requestPhone(): Promise<string | null> {
  return new Promise(resolve => {
    if (!tg?.requestContact) return resolve(null)
    tg.requestContact((ok, res) => {
      const phone = ok && res && 'responseUnsafe' in res ? res.responseUnsafe.contact.phone_number : null
      resolve(phone ? (phone.startsWith('+') ? phone : '+' + phone) : null)
    })
  })
}
