import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RiskStatusPanel } from './RiskStatusPanel';
import { RiskStatus } from '../types/dashboard';

const mockRisk: RiskStatus = {
  emergency_stop: false,
  circuit_breaker_active: false,
  daily_pnl: -300.0,
  daily_loss_limit: 1000.0,
  current_exposure: 40000.0,
  max_exposure: 100000.0,
};

describe('RiskStatusPanel Component', () => {
  it('renders risk thresholds and limit utilization', () => {
    render(<RiskStatusPanel riskStatus={mockRisk} />);

    expect(screen.getByTestId('risk-status-panel')).toBeInTheDocument();
    expect(screen.getByTestId('circuit-breaker-badge')).toHaveTextContent(/Circuit Breakers Normal/i);
    expect(screen.getByTestId('daily-loss-value')).toHaveTextContent('-$300 / $1,000');
    expect(screen.getByTestId('exposure-value')).toHaveTextContent('$40,000 / $100,000');
  });

  it('triggers emergency stop callback on button click', () => {
    const handleToggle = vi.fn();
    render(<RiskStatusPanel riskStatus={mockRisk} onToggleEmergencyStop={handleToggle} />);

    const btn = screen.getByTestId('emergency-stop-toggle-btn');
    expect(btn).toHaveTextContent(/Engage Emergency Stop/i);

    fireEvent.click(btn);
    expect(handleToggle).toHaveBeenCalledWith(true);
  });

  it('displays tripped state when circuit breaker fires', () => {
    const trippedRisk: RiskStatus = {
      ...mockRisk,
      circuit_breaker_active: true,
      emergency_stop: true,
    };
    render(<RiskStatusPanel riskStatus={trippedRisk} />);

    expect(screen.getByTestId('circuit-breaker-badge')).toHaveTextContent(/Circuit Breaker TRIPPED/i);
    expect(screen.getByTestId('emergency-stop-toggle-btn')).toHaveTextContent(/Deactivate Stop/i);
  });
});
