import { useEffect, useState, useRef, useCallback } from 'react'
import Editor, { loader } from '@monaco-editor/react'
import { config } from '../lib/api'
import { Check, AlertTriangle, X, RotateCcw, Save, FileCheck, Loader2, RefreshCw } from 'lucide-react'

// Multiple CDN sources for Monaco Editor with fallbacks
const CDN_SOURCES = [
    'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs',  // Primary (fastest)
    'https://unpkg.com/monaco-editor@0.45.0/min/vs',              // Fallback 1
    'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs'  // Fallback 2
]

// Initialize with first CDN source
loader.config({ paths: { vs: CDN_SOURCES[0] } })

export default function ConfigEditor() {
    const [yaml, setYaml] = useState('')
    const [etag, setEtag] = useState('')
    const [modified, setModified] = useState(false)
    const [validation, setValidation] = useState<{ valid: boolean; errors: Array<{ line: number; msg: string }>; warnings: Array<{ line: number; msg: string }> } | null>(null)
    const [saving, setSaving] = useState(false)
    const [status, setStatus] = useState<string>('')
    const [editorReady, setEditorReady] = useState(false)
    const [loadError, setLoadError] = useState(false)
    const [loadingCdn, setLoadingCdn] = useState<string | null>(CDN_SOURCES[0])
    const [retrying, setRetrying] = useState(false)
    const originalYaml = useRef('')
    const cdnIndexRef = useRef(0)

    // Try loading Monaco from CDN with fallbacks
    const tryLoadMonaco = useCallback(async (startIndex = 0) => {
        setRetrying(true)
        setLoadError(false)

        for (let i = startIndex; i < CDN_SOURCES.length; i++) {
            const cdn = CDN_SOURCES[i]
            cdnIndexRef.current = i
            setLoadingCdn(cdn)

            try {
                // Configure loader with current CDN
                loader.config({ paths: { vs: cdn } })

                // Try to initialize Monaco with 10s timeout per CDN
                await Promise.race([
                    loader.init(),
                    new Promise((_, reject) =>
                        setTimeout(() => reject(new Error('Timeout')), 10000)
                    )
                ])

                // Success!
                setLoadingCdn(null)
                setRetrying(false)
                return true
            } catch (err) {
                console.warn(`Monaco CDN failed (${cdn}):`, err)
            }
        }

        // All CDNs failed
        setLoadError(true)
        setLoadingCdn(null)
        setRetrying(false)
        return false
    }, [])

    // Retry button handler
    const handleRetryLoad = () => {
        setEditorReady(false)
        tryLoadMonaco(0)
    }

    useEffect(() => {
        config.get().then(res => {
            setYaml(res.yaml)
            setEtag(res.etag)
            originalYaml.current = res.yaml
        }).catch(() => setStatus('Failed to load config'))

        // Timeout for editor loading (30 seconds total)
        const timeout = setTimeout(() => {
            if (!editorReady && !loadError) {
                // Try next CDN if available
                const nextIndex = cdnIndexRef.current + 1
                if (nextIndex < CDN_SOURCES.length) {
                    tryLoadMonaco(nextIndex)
                } else {
                    setLoadError(true)
                }
            }
        }, 30000)

        return () => clearTimeout(timeout)
    }, [editorReady, loadError, tryLoadMonaco])

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
                {loadError ? (
                    <div className="flex flex-col items-center justify-center h-full" style={{ background: 'var(--color-bg-primary)', borderRadius: 6 }}>
                        <AlertTriangle size={32} style={{ color: 'var(--color-warning)' }} />
                        <p className="text-sm mt-3" style={{ color: 'var(--color-text-secondary)' }}>
                            Editor failed to load (all CDN sources unreachable)
                        </p>
                        <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                            Check your network connection and try again
                        </p>
                        <button
                            onClick={handleRetryLoad}
                            disabled={retrying}
                            className="flex items-center gap-2 mt-3 px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer disabled:opacity-50"
                            style={{ background: 'var(--color-accent)', color: '#fff' }}
                        >
                            <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
                            {retrying ? 'Retrying...' : 'Retry Loading Editor'}
                        </button>
                        <p className="text-xs mt-4 mb-2" style={{ color: 'var(--color-text-muted)' }}>
                            Or use the fallback text editor:
                        </p>
                        <textarea
                            className="w-full max-w-2xl h-64 p-3 rounded-lg font-mono text-xs"
                            style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)', border: '1px solid var(--color-border)' }}
                            value={yaml}
                            onChange={(e) => { setYaml(e.target.value); setModified(e.target.value !== originalYaml.current) }}
                            placeholder="YAML config will appear here..."
                        />
                    </div>
                ) : (
                    <Editor
                        height="100%"
                        language="yaml"
                        theme="vs-dark"
                        value={yaml}
                        onChange={(val) => { setYaml(val || ''); setModified(val !== originalYaml.current) }}
                        onMount={() => setEditorReady(true)}
                        loading={
                            <div className="flex flex-col items-center justify-center h-full" style={{ background: 'var(--color-bg-primary)' }}>
                                <div className="flex items-center">
                                    <Loader2 className="animate-spin" size={24} style={{ color: 'var(--color-accent)' }} />
                                    <span className="ml-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Loading editor...</span>
                                </div>
                                {loadingCdn && (
                                    <span className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                                        CDN: {loadingCdn.split('/')[2]}
                                    </span>
                                )}
                            </div>
                        }
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
                )}
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
