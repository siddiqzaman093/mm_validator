import { createContext, useContext, useState, useCallback } from 'react'
import { login as apiLogin, saveSession, restoreSession, clearSession } from '../api'

const AuthContext = createContext(null)

// Read once when the app loads: a refresh restores the session from
// sessionStorage instead of logging the user out.
const restored = restoreSession()

export function AuthProvider({ children }) {
  const [user, setUser] = useState(restored?.username ?? null)
  const [name, setName] = useState(restored?.name ?? null)
  const [role, setRole] = useState(restored?.role ?? null)
  const [error, setError] = useState('')

  const login = useCallback(async (username, password) => {
    setError('')
    try {
      // Trim stray whitespace (mobile keyboards often append a space).
      // Stored passwords never have edge whitespace — env values are stripped
      // server-side — so trimming the typed value is always safe.
      const data = await apiLogin(username.trim(), (password ?? '').trim())
      saveSession({
        token: data.access_token,
        username: data.username || username,
        name: data.name || '',
        role: data.role || 'user',
      })
      setUser(data.username || username)
      setName(data.name || '')
      setRole(data.role || 'user')
      return true
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Login failed. Check your credentials.'
      setError(msg)
      return false
    }
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setUser(null)
    setName(null)
    setRole(null)
    setError('')
  }, [])

  return (
    <AuthContext.Provider value={{ user, name, role, error, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
