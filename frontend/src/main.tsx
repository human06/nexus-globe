import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// StrictMode is intentionally omitted: Globe.GL (Three.js imperative renderer)
// is incompatible with React 18's double-mount behaviour in development.
createRoot(document.getElementById('root')!).render(<App />)
