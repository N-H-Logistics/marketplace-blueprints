import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

const root = document.getElementById('root');
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App agentName={root.dataset.agentName || 'RAG Assistant'} />
  </React.StrictMode>,
);
