import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DataExplorer from './DataExplorer';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DataExplorer />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
