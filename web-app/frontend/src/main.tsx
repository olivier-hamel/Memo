import React from 'react'
import ReactDOM from 'react-dom/client'
import StudyHome from './StudyHome'
import AuthGate from './AuthGate'
import { ValidationProvider } from './ValidationJobs'
import '@fontsource/dm-sans/latin-400.css'
import '@fontsource/dm-sans/latin-500.css'
import '@fontsource/dm-sans/latin-600.css'
import '@fontsource/dm-sans/latin-700.css'
import '@fontsource/lora/latin-400.css'
import '@fontsource/lora/latin-400-italic.css'
import '@fontsource/lora/latin-500.css'
import './styles.css'
import './sidebar.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><AuthGate><ValidationProvider><StudyHome /></ValidationProvider></AuthGate></React.StrictMode>,
)
