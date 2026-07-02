import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store/AuthContext'
import { ToastProvider } from './store/ToastContext'
import { ProtectedRoute } from './components/Layout'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { WatchListPage } from './pages/WatchListPage'
import { CreateWatchPage } from './pages/CreateWatchPage'
import { WatchDetailPage } from './pages/WatchDetailPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<Navigate to="/watches" replace />} />
              <Route path="/watches" element={<WatchListPage />} />
              <Route path="/watches/new" element={<CreateWatchPage />} />
              <Route path="/watches/:id" element={<WatchDetailPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
