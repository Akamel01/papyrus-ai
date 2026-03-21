import { useEffect, useState, useRef } from 'react'
import Editor from '@monaco-editor/react'
import { config } from '../lib/api'
import { Check, AlertTriangle, X, RotateCcw, Save, FileCheck } from 'lucide-react'

export default function ConfigEditor() {
    const [yaml, setYaml] = useState('')
    const [etag, setEtag] = useState('')
    const [modified, setModified] = useState(false)
    const [validation, setValidation] = useState<{ valid: boolean; errors: Array<{ line: number; msg: string }>; warnings: Array<{ line: number; msg: string }> } | null>(null)
    const [saving, setSaving] = useState(false)
    const [status, setStatus] = useState<string>('')
    const originalYaml = useRef('')

    useEffect(() => {
        config.get().then(res => {
            setYaml(res.yaml)
            setEtag(res.etag)
            originalYaml.current = res.yaml
        }).catch(() => setStatus('Failed to load config'))
    }, [])

    const handleValidate = async () => {
        try {
            const result = await config.validate(yaml)
            setValidation(result)
        } catch { setStatus('Validation request failed') }
    }

    const handleSave = async () => {
        setSaving(true)
        try {
            const result = await config.save(yaml, etag)
            setEtag(result.new_etag)
            originalYaml.current = yaml
            setModified(false)
            setStatus(`Saved (backup: ${result.backup_path})`)
            setTimeout(() => setStatus(''), 5000)
        } catch (e: unknown) {
            setStatus(`Save failed: ${e instanceof Error ? e.message : 'Unknown error'}`)
        } finally { setSaving(false) }
    }

    const handleRevert = () => {
        setYaml(originalYaml.current)
        setModified(false)
        setValidation(null)
        setStatus('Reverted to last saved version')
        setTimeout(() => setStatus(''), 3000)
    }

    return (
        <div className="space-y-3 h-full flex flex-col">
            {/* Toolbar */}
            <div className="card-compact flex items-center justify-between shrink-0">
                <div className="flex items-center gap-3">
                    <h2 className="text-sm font-semibold">Config Editor</h2>
                    {modified && (
                        <span className="text-xs px-2 py-0.5 rounded-full"
                            style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--color-warning)' }}>
                            ● Modified
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={handleValidate}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                        style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                        <FileCheck size={14} /> Validate
                    </button>
                    <button onClick={handleRevert} disabled={!modified}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-40"
                        style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                        <RotateCcw size={14} /> Revert
                    </button>
                    <button onClick={handleSave} disabled={saving || !modified}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-40"
                        style={{ background: 'var(--color-accent)', color: '#fff' }}>
                        <Save size={14} /> {saving ? 'Saving…' : 'Save'}
                    </button>
                </div>
            </div>

            {/* Status */}
            {status && (
                <div className="text-xs px-3 py-2 rounded-lg" style={{
                    background: status.includes('fail') || status.includes('Failed')
                        ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)',
                    color: status.includes('fail') || status.includes('Failed')
                        ? 'var(--color-error)' : 'var(--color-success)',
                }}>{status}</div>
            )}

            {/* Editor */}
            <div className="monaco-container flex-1 min-h-0">
                <Editor
                    height="100%"
                    language="yaml"
                    theme="vs-dark"
                    value={yaml}
                    onChange={(val) => { setYaml(val || ''); setModified(val !== originalYaml.current) }}
                    options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        fontFamily: 'JetBrains Mono, Fira Code, monospace',
                        lineNumbers: 'on',
                        scrollBeyondLastLine: false,
                        wordWrap: 'on',
                        tabSize: 2,
                        renderLineHighlight: 'gutter',
                        padding: { top: 8 },
                    }}
                />
            </div>

            {/* Validation Panel */}
            {validation && (
                <div className="card-compact shrink-0 max-h-40 overflow-y-auto">
                    <div className="flex items-center gap-2 mb-2">
                        {validation.valid
                            ? <><Check size={14} style={{ color: 'var(--color-success)' }} /><span className="text-xs" style={{ color: 'var(--color-success)' }}>YAML valid</span></>
                            : <><X size={14} style={{ color: 'var(--color-error)' }} /><span className="text-xs" style={{ color: 'var(--color-error)' }}>{validation.errors.length} error(s)</span></>
                        }
                    </div>
                    {validation.errors.map((e, i) => (
                        <div key={i} className="text-xs flex items-start gap-2 py-1" style={{ color: 'var(--color-error)' }}>
                            <X size={12} className="mt-0.5 shrink-0" /> Line {e.line}: {e.msg}
                        </div>
                    ))}
                    {validation.warnings.map((w, i) => (
                        <div key={i} className="text-xs flex items-start gap-2 py-1" style={{ color: 'var(--color-warning)' }}>
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {w.msg}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
