import { Routes, Route, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import ConfigEditor from './pages/ConfigEditor'
import RunControls from './pages/RunControls'
import CoverageMap from './pages/CoverageMap'
import Metrics from './pages/Metrics'
import Admin from './pages/Admin'
import MyDocuments from './pages/MyDocuments'
import { dashboardWS } from './lib/websocket'

function App() {
  const [authed, setAuthed] = useState(!!localStorage.getItem('access_token'))

  useEffect(() => {
    if (authed) {
      dashboardWS.connect()
      return () => dashboardWS.disconnect()
    }
  }, [authed])

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/config" element={<ConfigEditor />} />
        <Route path="/runs" element={<RunControls />} />
        <Route path="/coverage" element={<CoverageMap />} />
        <Route path="/metrics" element={<Metrics />} />
        <Route path="/documents" element={<MyDocuments />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App
