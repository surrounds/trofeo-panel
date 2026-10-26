// Конфигуратор панели Trofeo Vision 11.3: 4 слота, в каждом свой виджет.
// Предпросмотр рендерится бекендом (POST /api/preview.png с черновиком).
// Язык интерфейса: EN (по умолчанию) / UK, хранится в config.language.
import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

const SLOTS = 4

// Слот с выбранным "нет" в конфиг не попадает (панелей может быть 1..4)
// offline - виджет слота на время, когда нет связи с приложением
function slotsToPanels(slots) {
  return slots.filter((s) => s.type !== 'none')
    .map((s) => ({
      type: s.type,
      settings: s.settings,
      offline: s.offline && s.offline.type !== 'none'
        ? { type: s.offline.type, settings: s.offline.settings }
        : null,
    }))
}

function panelsToSlots(panels) {
  const slots = panels.map((p) => ({
    type: p.type,
    settings: p.settings || {},
    offline: p.offline ? { type: p.offline.type, settings: p.offline.settings || {} } : null,
  }))
  while (slots.length < SLOTS) slots.push({ type: 'none', settings: {}, offline: null })
  return slots.slice(0, SLOTS)
}

// Настройки виджета по схеме из /api/widgets
function WidgetSettings({ schema, settings, images, lang, onChange }) {
  const entries = Object.entries(schema || {})
  const uk = lang === 'uk'
  const title = (meta) => (uk && meta.title_uk) || meta.title
  if (!entries.length) return null
  return (
    <div className="settings">
      {entries.map(([key, meta]) => {
        const value = settings[key] ?? meta.default
        if (meta.type === 'bool') {
          return (
            <label key={key} className="row">
              <input
                type="checkbox"
                checked={!!value}
                onChange={(e) => onChange(key, e.target.checked)}
              />
              {title(meta)}
            </label>
          )
        }
        if (meta.type === 'enum') {
          return (
            <label key={key} className="row">
              {title(meta)}
              <select value={value ?? ''} onChange={(e) => onChange(key, e.target.value)}>
                {meta.values.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
          )
        }
        if (meta.type === 'image') {
          return (
            <label key={key} className="row">
              {title(meta)}
              <select value={value ?? ''} onChange={(e) => onChange(key, e.target.value || null)}>
                <option value="">{uk ? 'не вибрано' : 'none selected'}</option>
                {images.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </label>
          )
        }
        if (meta.type === 'zonelist') {
          const list = Array.isArray(value)
            ? value
            : typeof value === 'string'
              ? value.split('\n').map((s) => s.split('|')[0].trim()).filter(Boolean)
              : []
          const max = meta.max ?? 6
          const optLabel = (o) => (uk && o.label_uk) || o.label
          return (
            <div key={key} className="zonelist">
              <div className="row-title">{title(meta)}</div>
              {list.map((tz, idx) => (
                <div className="row" key={idx}>
                  <select
                    value={tz}
                    onChange={(e) => {
                      const next = [...list]
                      next[idx] = e.target.value
                      onChange(key, next)
                    }}
                  >
                    {meta.options.map((o) => (
                      <option key={o.value} value={o.value}>{optLabel(o)}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="mini"
                    title={uk ? 'Прибрати місто' : 'Remove city'}
                    onClick={() => onChange(key, list.filter((_, j) => j !== idx))}
                  >
                    ✕
                  </button>
                </div>
              ))}
              {list.length < max && (
                <button
                  type="button"
                  className="mini add"
                  onClick={() => {
                    const used = new Set(list)
                    const free = meta.options.find((o) => !used.has(o.value))
                    onChange(key, [...list, (free ?? meta.options[0]).value])
                  }}
                >
                  {uk ? '+ місто' : '+ city'}
                </button>
              )}
            </div>
          )
        }
        if (meta.type === 'text') {
          return (
            <label key={key} className="row col">
              {title(meta)}
              <textarea
                rows={4}
                value={value ?? ''}
                onChange={(e) => onChange(key, e.target.value)}
              />
            </label>
          )
        }
        return (
          <label key={key} className="row">
            {title(meta)}
            <input
              type="text"
              value={value ?? ''}
              onChange={(e) => onChange(key, e.target.value)}
            />
          </label>
        )
      })}
    </div>
  )
}

export default function App() {
  const [catalog, setCatalog] = useState([])
  const [images, setImages] = useState([])
  const [slots, setSlots] = useState(null)
  const [saved, setSaved] = useState(null)     // последний сохранённый конфиг
  const [lang, setLang] = useState('en')
  const [status, setStatus] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const previewTimer = useRef(null)
  const previewBlobUrl = useRef(null)

  const uk = lang === 'uk'
  const t = (en, ukr) => (uk ? ukr : en)

  // Начальная загрузка: каталог, конфиг, картинки
  useEffect(() => {
    Promise.all([
      fetch('/api/widgets').then((r) => r.json()),
      fetch('/api/config').then((r) => r.json()),
      fetch('/api/images').then((r) => r.json()),
    ]).then(([cat, cfg, imgs]) => {
      setCatalog(cat)
      setImages(imgs)
      setSaved(cfg)
      setLang(cfg.language === 'uk' ? 'uk' : 'en')
      setSlots(panelsToSlots(cfg.panels))
    }).catch((e) => setError(`Backend unavailable: ${e}`))
  }, [])

  // Статус панели раз в 3 секунды
  useEffect(() => {
    const tick = () =>
      fetch('/api/status').then((r) => r.json()).then(setStatus).catch(() => setStatus(null))
    tick()
    const id = setInterval(tick, 3000)
    return () => clearInterval(id)
  }, [])

  // Предпросмотр черновика с дебаунсом
  const refreshPreview = useCallback((slotsNow, savedNow, langNow) => {
    if (!slotsNow || !savedNow) return
    clearTimeout(previewTimer.current)
    previewTimer.current = setTimeout(async () => {
      const panels = slotsToPanels(slotsNow)
      if (!panels.length) return
      try {
        const r = await fetch('/api/preview.png', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...savedNow, language: langNow, panels }),
        })
        if (!r.ok) throw new Error(await r.text())
        const blob = await r.blob()
        if (previewBlobUrl.current) URL.revokeObjectURL(previewBlobUrl.current)
        previewBlobUrl.current = URL.createObjectURL(blob)
        setPreviewUrl(previewBlobUrl.current)
        setError(null)
      } catch (e) {
        setError(`Preview error: ${e.message}`)
      }
    }, 300)
  }, [])

  useEffect(() => { refreshPreview(slots, saved, lang) }, [slots, saved, lang, refreshPreview])

  if (!slots) {
    return <div className="app"><p className="error">{error || 'Loading...'}</p></div>
  }

  const setSlot = (i, patch) => {
    setSlots((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  }

  // Дефолтные настройки виджета из каталога
  const defaultsFor = (type) => {
    const meta = catalog.find((w) => w.type === type)
    const settings = {}
    for (const [k, m] of Object.entries(meta?.settings || {})) {
      if (m.default !== null && m.default !== undefined) settings[k] = m.default
    }
    return settings
  }

  const changeType = (i, type) => {
    // При смене типа настройки сбрасываются на дефолтные из каталога
    setSlot(i, { type, settings: defaultsFor(type) })
  }

  const changeOffline = (i, type) => {
    setSlot(i, { offline: type === 'none' ? null : { type, settings: defaultsFor(type) } })
  }

  const save = async (override = {}) => {
    const panels = slotsToPanels(slots)
    if (!panels.length) {
      setError(t('At least one widget is required', 'Потрібен хоча б один віджет'))
      return
    }
    setSaving(true)
    try {
      const r = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...saved, language: lang, ...override, panels }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => null)
        throw new Error(d?.detail?.[0]?.msg || r.statusText)
      }
      setSaved(await r.json())
      setError(null)
    } catch (e) {
      setError(`${t('Save failed', 'Не збереглося')}: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const changeLang = (v) => {
    setLang(v)
    // Язык применяется и сохраняется сразу
    save({ language: v })
  }

  const dirty = saved && (
    JSON.stringify(slotsToPanels(slots)) !== JSON.stringify(saved.panels) ||
    lang !== saved.language
  )

  const widgetTitle = (w) => (uk && w.title_uk) || w.title

  return (
    <div className="app">
      <header>
        <h1>Trofeo Vision 11.3</h1>
        <div className="header-right">
          <select
            className="lang"
            value={lang}
            onChange={(e) => changeLang(e.target.value)}
          >
            <option value="en">EN</option>
            <option value="uk">UK</option>
          </select>
          <div className={`status ${status?.connected ? 'ok' : 'off'}`}>
            {status
              ? status.connected
                ? `${t('panel connected, frames:', 'панель підключена, кадрів:')} ${status.frames_sent}`
                : status.usb_enabled
                  ? `${t('panel not connected', 'панель не підключена')}${status.last_error ? `: ${status.last_error}` : ''}`
                  : t('no-USB mode', 'режим без USB')
              : t('backend unreachable', 'немає зв’язку з бекендом')}
          </div>
        </div>
      </header>

      <div className="preview">
        {previewUrl
          ? <img src={previewUrl} alt="Panel frame preview 1920x440" />
          : <div className="preview-empty">{t('Preview...', 'Попередній перегляд...')}</div>}
      </div>

      <div className="slots">
        {slots.map((slot, i) => {
          const meta = catalog.find((w) => w.type === slot.type)
          return (
            <div className="slot" key={i}>
              <div className="slot-head">{t('SLOT', 'ЧАСТИНА')} {i + 1}</div>
              <select value={slot.type} onChange={(e) => changeType(i, e.target.value)}>
                <option value="none">{t('none', 'немає')}</option>
                {catalog.map((w) => (
                  <option key={w.type} value={w.type}>{widgetTitle(w)}</option>
                ))}
              </select>
              <WidgetSettings
                schema={meta?.settings}
                settings={slot.settings}
                images={images}
                lang={lang}
                onChange={(k, v) =>
                  setSlot(i, { settings: { ...slot.settings, [k]: v } })}
              />
              {slot.type !== 'none' && (
                <>
                  <div className="slot-sub">{t('When disconnected', 'Без зв\u2019язку')}</div>
                  <select
                    value={slot.offline?.type ?? 'none'}
                    onChange={(e) => changeOffline(i, e.target.value)}
                  >
                    <option value="none">{t('same widget (No data)', 'той самий (No data)')}</option>
                    {catalog.map((w) => (
                      <option key={w.type} value={w.type}>{widgetTitle(w)}</option>
                    ))}
                  </select>
                  {slot.offline && (
                    <WidgetSettings
                      schema={catalog.find((w) => w.type === slot.offline.type)?.settings}
                      settings={slot.offline.settings}
                      images={images}
                      lang={lang}
                      onChange={(k, v) => setSlot(i, {
                        offline: { ...slot.offline, settings: { ...slot.offline.settings, [k]: v } },
                      })}
                    />
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>

      <footer>
        {error && <span className="error">{error}</span>}
        <button onClick={() => save()} disabled={!dirty || saving}>
          {saving
            ? t('Saving...', 'Зберігаю...')
            : dirty
              ? t('Save to panel', 'Зберегти на панель')
              : t('Saved', 'Збережено')}
        </button>
      </footer>
    </div>
  )
}
