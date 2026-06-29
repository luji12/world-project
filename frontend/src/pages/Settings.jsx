import { useState } from 'react'
import { CheckCircle2, KeyRound, LockKeyhole, Settings as SettingsIcon } from 'lucide-react'
import { useSettings } from '../SettingsContext'
import { Button, TextInput } from '../components/UI'
import { KeyValue, Surface, WorkspaceHeader, WorkspacePage } from '../components/Atelier'

export default function Settings() {
  const { settings, updateSettings } = useSettings()
  const [saved, setSaved] = useState(false)
  const [apiKey, setApiKey] = useState(settings.apiKey)
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl)
  const [model, setModel] = useState(settings.model)

  function handleSave(event) {
    event.preventDefault()
    updateSettings({
      apiKey: apiKey.trim(),
      baseUrl: baseUrl.trim() || 'https://api.deepseek.com',
      model: model.trim() || 'deepseek-chat',
    })
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }

  return (
    <WorkspacePage className="max-w-4xl">
      <WorkspaceHeader trail="系统设置" title="模型配置" description="连接叙事引擎。配置只留在当前浏览器，不会写入项目文件。" />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <Surface>
          <form onSubmit={handleSave} className="space-y-6 p-5 md:p-7">
            <div className="flex items-start gap-3 border-l border-[#d3ad65]/45 pl-3">
              <LockKeyhole aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[#d3ad65]" />
              <p className="text-sm leading-6 text-[#a99f8c]">密钥会用于本机发起模型请求；界面只显示掩码后的状态。</p>
            </div>

            <label className="block">
              <span className="atelier-field-label">API Key</span>
              <TextInput id="apiKey" type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder="sk-..." className="w-full font-mono" autoComplete="off" />
            </label>
            <label className="block">
              <span className="atelier-field-label">Base URL</span>
              <TextInput id="baseUrl" type="text" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://api.deepseek.com" className="w-full font-mono" />
            </label>
            <label className="block">
              <span className="atelier-field-label">Model</span>
              <TextInput id="model" type="text" value={model} onChange={event => setModel(event.target.value)} placeholder="deepseek-chat" className="w-full font-mono" />
            </label>

            <div className="flex flex-wrap items-center gap-3 border-t border-[#d6ccba]/14 pt-5">
              <Button type="submit" tone="primary" icon={KeyRound}>保存连接</Button>
              {saved && <span className="inline-flex items-center gap-1.5 text-sm text-emerald-200" role="status"><CheckCircle2 aria-hidden="true" className="h-4 w-4" />已保存</span>}
            </div>
          </form>
        </Surface>

        <Surface className="h-fit p-5">
          <div className="flex items-center gap-2 text-[#d3ad65]"><SettingsIcon aria-hidden="true" className="h-4 w-4" /><span className="text-xs font-semibold tracking-[.14em]">连接摘要</span></div>
          <div className="mt-5 space-y-5">
            <KeyValue label="API Key" value={settings.apiKey ? `${settings.apiKey.slice(0, 7)}···${settings.apiKey.slice(-4)}` : '未设置'} />
            <KeyValue label="BASE URL" value={settings.baseUrl || '未设置'} />
            <KeyValue label="MODEL" value={settings.model || '未设置'} />
          </div>
        </Surface>
      </div>
    </WorkspacePage>
  )
}
