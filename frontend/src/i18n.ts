// Interface language for regions that offer one (hk). Simplified Chinese is the source text.
// Traditional Chinese is converted with OpenCC (Hong Kong variant); English uses the table in i18n-en.ts and
// falls back to the Simplified source for text that has no translation yet.
// Only interface copy goes through t(); contract quotes, statute text and model output never do.
import { ref, watch } from 'vue'
import { EN } from './i18n-en'

export type Lang = 'zh-Hans' | 'zh-Hant' | 'en'
export const LANGS: { value: Lang, label: string, report: string }[] = [
  { value: 'zh-Hans', label: '简体', report: '简体中文' },
  { value: 'zh-Hant', label: '繁體', report: '繁體中文' },
  { value: 'en', label: 'ENG', report: 'English' },
]
const KEY = 'ui-language'

function saved(): Lang {
  try {
    const value = localStorage.getItem(KEY)
    if (value === 'zh-Hans' || value === 'zh-Hant' || value === 'en') return value
  } catch { /* storage unavailable: use the default */ }
  return 'zh-Hans'
}

export const lang = ref<Lang>(saved())
// Set by App once the region profile is known; mainland always renders the source text.
export const enabled = ref(false)

watch(lang, value => {
  try { localStorage.setItem(KEY, value) } catch { /* the choice just won't persist */ }
}, { flush: 'sync' })
watch([lang, enabled], ([value, on]) => {
  document.documentElement.lang = on ? value : 'zh-CN'
}, { immediate: true })

// The converter's dictionaries are large, so they load only when Traditional Chinese is chosen.
let toHant: ((text: string) => string) | null = null
const converterReady = ref(false)
watch([lang, enabled], ([value, on]) => {
  if (on && value === 'zh-Hant' && !toHant) {
    import('opencc-js/cn2t').then(OpenCC => {
      toHant = OpenCC.Converter({ from: 'cn', to: 'hk' })
      converterReady.value = true
    })
  }
}, { immediate: true })
const hant = new Map<string, string>()
// OpenCC's hk variant keeps 税/用户 and writes 説; Hong Kong government text uses 稅, 用戶 and 說.
const fix = (text: string) => text.replace(/税/g, '稅').replace(/説/g, '說').replace(/用户/g, '用戶')

export function t(text?: string | null, vars?: Record<string, string | number>): string {
  if (!text) return text ?? ''
  let out = text
  if (enabled.value && lang.value === 'en') out = EN[text] ?? text
  else if (enabled.value && lang.value === 'zh-Hant' && converterReady.value && toHant) {
    if (!hant.has(text)) hant.set(text, fix(toHant(text)))
    out = hant.get(text)!
  }
  return vars ? out.replace(/\{(\w+)\}/g, (match, key) => key in vars ? String(vars[key]) : match) : out
}
