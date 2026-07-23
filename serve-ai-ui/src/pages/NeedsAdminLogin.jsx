/**
 * NeedsAdminLogin — Token entry for needs coordination team.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const NEEDS_TOKEN_KEY = 'serve_needs_admin_token';

export function NeedsAdminLogin() {
  const [inputToken, setInputToken] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  // Already logged in
  if (localStorage.getItem(NEEDS_TOKEN_KEY)) {
    navigate('/needs-admin/dashboard', { replace: true });
    return null;
  }

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputToken.trim()) {
      setError('Please enter a token');
      return;
    }
    localStorage.setItem(NEEDS_TOKEN_KEY, inputToken.trim());
    navigate('/needs-admin/dashboard');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
      <div className="max-w-sm w-full">
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-lg bg-emerald-600 flex items-center justify-center mx-auto mb-4">
            <span className="text-white font-bold text-xl">N</span>
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Needs Operations</h1>
          <p className="text-sm text-slate-500 mt-1">Enter your needs admin token</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="password"
              value={inputToken}
              onChange={(e) => { setInputToken(e.target.value); setError(''); }}
              placeholder="Needs admin token"
              className="w-full px-4 py-3 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
              autoFocus
            />
            {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
          </div>
          <button
            type="submit"
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Enter
          </button>
        </form>

        <p className="text-center text-xs text-slate-400 mt-6">
          <a href="/" className="hover:text-slate-600">← Back to volunteer chat</a>
        </p>
      </div>
    </div>
  );
}

export default NeedsAdminLogin;
