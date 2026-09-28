import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { PnLChart } from './PnLChart';
import { EquityCurvePoint } from '../types/dashboard';

const mockCurve: EquityCurvePoint[] = [
  { timestamp: '2026-08-01', equity: 100000, drawdown: 0.0, exposure: 40000 },
  { timestamp: '2026-08-02', equity: 105000, drawdown: 0.0, exposure: 42000 },
  { timestamp: '2026-08-03', equity: 102000, drawdown: 0.0285, exposure: 41000 },
  { timestamp: '2026-08-04', equity: 110000, drawdown: 0.0, exposure: 45000 },
];

describe('PnLChart Component', () => {
  it('renders SVG chart and summary statistics', () => {
    render(<PnLChart data={mockCurve} />);

    expect(screen.getByTestId('pnl-chart-panel')).toBeInTheDocument();
    expect(screen.getByTestId('pnl-chart-svg')).toBeInTheDocument();
    expect(screen.getByTestId('net-return')).toHaveTextContent('+10.00%');
    expect(screen.getByTestId('max-drawdown')).toHaveTextContent('-2.85%');
    expect(screen.getByTestId('peak-equity')).toHaveTextContent('$110,000');
  });

  it('renders loading state when specified', () => {
    render(<PnLChart data={[]} loading={true} />);
    expect(screen.getByText(/Loading equity curve telemetry/i)).toBeInTheDocument();
  });
});
