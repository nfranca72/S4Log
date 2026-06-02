import { useCallback, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import Layout from './components/layout/Layout'
import SplashScreen from './components/SplashScreen'
import Module1 from './pages/Module1'
import Module2 from './pages/Module2'
import Module3 from './pages/Module3'
import Config from './pages/Config'
import Labels from './pages/Labels'
import SAPB1 from './pages/SAPB1'

const SPLASH_SESSION_KEY = 's4log:splash-seen'

function hasSeenSplash() {
  try {
    return window.sessionStorage.getItem(SPLASH_SESSION_KEY) === '1'
  } catch {
    return false
  }
}

export default function App() {
  const [splashDone, setSplashDone] = useState(hasSeenSplash)
  const completeSplash = useCallback(() => {
    try {
      window.sessionStorage.setItem(SPLASH_SESSION_KEY, '1')
    } catch {
      // sessionStorage can be blocked; the splash should still complete.
    }
    setSplashDone(true)
  }, [])

  return (
    <ToastProvider>
      {!splashDone && <SplashScreen onComplete={completeSplash} />}
      <Layout>
        <Routes>
          <Route path="/"           element={<Navigate to="/importacao" replace />} />
          <Route path="/importacao" element={<Module1 />} />
          <Route path="/recepcao"   element={<Module2 />} />
          <Route path="/consulta"   element={<Module3 />} />
          <Route path="/etiquetas"  element={<Labels />} />
          <Route path="/sap-b1" element={<SAPB1 />} />
          <Route path="/configuracao" element={<Config />} />
        </Routes>
      </Layout>
    </ToastProvider>
  )
}
