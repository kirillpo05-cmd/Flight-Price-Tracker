import { useState, FormEvent } from 'react'
import { patchMe, changePassword, deleteMe } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import { useToast } from '../store/ToastContext'

const PLAN_LABEL: Record<string, string> = {
  free: 'Free',
  pro: 'Pro',
  team: 'Team',
}
const PLAN_COLOR: Record<string, string> = {
  free: 'bg-gray-100 text-gray-700',
  pro: 'bg-blue-100 text-blue-700',
  team: 'bg-purple-100 text-purple-700',
}

export function SettingsPage() {
  const { user, refresh, logout } = useAuth()
  const toast = useToast()

  const [chatId, setChatId] = useState(user?.telegram_chat_id?.toString() ?? '')
  const [savingTg, setSavingTg] = useState(false)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [savingPw, setSavingPw] = useState(false)
  const [pwError, setPwError] = useState('')

  const handleSaveTelegram = async (e: FormEvent) => {
    e.preventDefault()
    setSavingTg(true)
    try {
      await patchMe({
        telegram_chat_id: chatId ? parseInt(chatId) : null,
      })
      await refresh()
      toast('Telegram settings saved', 'success')
    } catch {
      toast('Failed to save Telegram settings', 'error')
    } finally {
      setSavingTg(false)
    }
  }

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault()
    setPwError('')
    if (newPw !== confirmPw) {
      setPwError('Passwords do not match')
      return
    }
    if (newPw.length < 8) {
      setPwError('Password must be at least 8 characters')
      return
    }
    setSavingPw(true)
    try {
      await changePassword(currentPw, newPw)
      toast('Password updated', 'success')
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err: any) {
      const msg = err.response?.data?.detail
      setPwError(typeof msg === 'string' ? msg : 'Failed to change password')
    } finally {
      setSavingPw(false)
    }
  }

  const handleDeleteAccount = async () => {
    if (!confirm('Permanently delete your account and all data? This cannot be undone.')) return
    if (!confirm('Are you absolutely sure?')) return
    try {
      await deleteMe()
      logout()
    } catch {
      toast('Failed to delete account', 'error')
    }
  }

  const plan = user?.plan ?? 'free'

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

      {/* Profile */}
      <Card title="Profile">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900">{user?.email}</p>
            <p className="text-xs text-gray-400 mt-0.5">Member since {user?.created_at?.slice(0, 10)}</p>
          </div>
          <span className={`text-xs font-bold px-3 py-1 rounded-full uppercase ${PLAN_COLOR[plan]}`}>
            {PLAN_LABEL[plan]}
          </span>
        </div>
      </Card>

      {/* Telegram */}
      <Card title="Telegram Notifications">
        {user?.telegram_chat_id ? (
          <div className="flex items-center gap-2 mb-4">
            <span className="text-green-600 font-semibold text-sm">Connected</span>
            <span className="text-xs text-gray-400">(Chat ID: {user.telegram_chat_id})</span>
          </div>
        ) : (
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 mb-4 text-sm text-blue-800">
            <p className="font-medium mb-1">How to connect Telegram:</p>
            <ol className="list-decimal list-inside space-y-1 text-xs">
              <li>Open Telegram and search for your bot</li>
              <li>Send /start to the bot</li>
              <li>The bot will reply with your Chat ID</li>
              <li>Paste it below and save</li>
            </ol>
          </div>
        )}
        <form onSubmit={handleSaveTelegram} className="flex gap-2">
          <input
            type="number"
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder="Chat ID"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={savingTg}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {savingTg ? 'Saving…' : 'Save'}
          </button>
          {user?.telegram_chat_id && (
            <button
              type="button"
              disabled={savingTg}
              onClick={async () => {
                setChatId('')
                setSavingTg(true)
                try {
                  await patchMe({ telegram_chat_id: null })
                  await refresh()
                  toast('Telegram disconnected', 'success')
                } catch {
                  toast('Failed to disconnect', 'error')
                } finally {
                  setSavingTg(false)
                }
              }}
              className="px-3 py-2 border border-gray-200 text-gray-500 text-sm rounded-lg hover:bg-gray-50 transition-colors"
            >
              Disconnect
            </button>
          )}
        </form>
      </Card>

      {/* Change password */}
      <Card title="Change Password">
        {pwError && (
          <p className="text-sm text-red-600 mb-3">{pwError}</p>
        )}
        <form onSubmit={handleChangePassword} className="space-y-3">
          <input
            type="password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            placeholder="Current password"
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            placeholder="New password (min 8 chars)"
            required
            minLength={8}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="password"
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            placeholder="Confirm new password"
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={savingPw}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {savingPw ? 'Saving…' : 'Change Password'}
          </button>
        </form>
      </Card>

      {/* Danger zone */}
      <Card title="Danger Zone">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-900">Delete account</p>
            <p className="text-xs text-gray-400">Permanently delete all data</p>
          </div>
          <button
            onClick={handleDeleteAccount}
            className="px-3 py-1.5 border border-red-200 text-red-600 text-sm rounded-lg hover:bg-red-50 transition-colors font-medium"
          >
            Delete account
          </button>
        </div>
      </Card>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">{title}</h2>
      {children}
    </div>
  )
}
