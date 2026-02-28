import WebApp from '@twa-dev/sdk'

export function initTelegram() {
  WebApp.ready()
  WebApp.expand()
}

export function getTelegramTheme() {
  return {
    bgColor: WebApp.themeParams.bg_color || '#ffffff',
    textColor: WebApp.themeParams.text_color || '#000000',
    hintColor: WebApp.themeParams.hint_color || '#999999',
    buttonColor: WebApp.themeParams.button_color || '#3390ec',
    buttonTextColor: WebApp.themeParams.button_text_color || '#ffffff',
  }
}

export function getInitData(): { date?: string; mode?: string } {
  const params = new URLSearchParams(WebApp.initData)
  const startParam = params.get('start_param') || ''
  // Format: "dayplanner_2026-02-28" or "playground"
  const [mode, date] = startParam.split('_')
  return { mode: mode || 'dayplanner', date }
}
