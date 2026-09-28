import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { StrategyStatusPanel } from './StrategyStatusPanel';
import { StrategySummary } from '../types/dashboard';

const mockStrategies: StrategySummary[] = [
  {
    name: 'Alpha Momentum',
    version: '1.0.0',
    active: true,
    config: { window: 20 },
    metrics: { win_rate: 0.62, sharpe: 2.1, total_trades: 50 },
  },
  {
    name: 'Beta Reversion',
    version: '0.8.0',
    active: false,
    config: { z_threshold: 2.5 },
    metrics: { win_rate: 0.51, sharpe: 1.2, total_trades: 30 },
  },
];

describe('StrategyStatusPanel Component', () => {
  it('renders strategies with metrics and version tags', () => {
    render(<StrategyStatusPanel strategies={mockStrategies} />);

    expect(screen.getByText('Alpha Momentum')).toBeInTheDocument();
    expect(screen.getByText('Beta Reversion')).toBeInTheDocument();
    expect(screen.getByText('2.10')).toBeInTheDocument();
    expect(screen.getByText('62%')).toBeInTheDocument();
  });

  it('triggers onToggleStrategy callback when toggle clicked', () => {
    const handleToggle = vi.fn();
    render(
      <StrategyStatusPanel
        strategies={mockStrategies}
        onToggleStrategy={handleToggle}
      />
    );

    const toggleAlpha = screen.getByTestId('strategy-toggle-alpha-momentum');
    fireEvent.click(toggleAlpha);
    expect(handleToggle).toHaveBeenCalledWith('Alpha Momentum', false);

    const toggleBeta = screen.getByTestId('strategy-toggle-beta-reversion');
    fireEvent.click(toggleBeta);
    expect(handleToggle).toHaveBeenCalledWith('Beta Reversion', true);
  });
});
