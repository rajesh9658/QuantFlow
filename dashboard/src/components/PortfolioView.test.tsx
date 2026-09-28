import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { PortfolioView } from './PortfolioView';
import { PortfolioSnapshot } from '../types/dashboard';

const mockPortfolio: PortfolioSnapshot = {
  cash: 75000.0,
  total_equity: 125000.0,
  total_exposure: 50000.0,
  realized_pnl: 15000.0,
  unrealized_pnl: 3500.0,
  positions: [
    { symbol: 'BTC/USDT', quantity: 1.0, avg_entry_price: 50000.0, unrealized_pnl: 2500.0 },
    { symbol: 'ETH/USDT', quantity: 5.0, avg_entry_price: 3000.0, unrealized_pnl: 1000.0 },
  ],
};

describe('PortfolioView Component', () => {
  it('renders portfolio summary metrics correctly with fixture data', () => {
    render(<PortfolioView portfolio={mockPortfolio} />);

    expect(screen.getByTestId('total-equity')).toHaveTextContent('$125,000.00');
    expect(screen.getByTestId('cash-value')).toHaveTextContent('$75,000.00');
    expect(screen.getByTestId('realized-pnl')).toHaveTextContent('+$15,000.00');
    expect(screen.getByTestId('unrealized-pnl')).toHaveTextContent('+$3,500.00');
    expect(screen.getByTestId('total-exposure')).toHaveTextContent('$50,000.00');
  });

  it('renders position rows with correct symbols and values', () => {
    render(<PortfolioView portfolio={mockPortfolio} />);

    expect(screen.getByTestId('position-row-BTC-USDT')).toBeInTheDocument();
    expect(screen.getByTestId('position-row-ETH-USDT')).toBeInTheDocument();
    expect(screen.getByText('BTC/USDT')).toBeInTheDocument();
    expect(screen.getByText('ETH/USDT')).toBeInTheDocument();
  });

  it('handles empty positions gracefully', () => {
    const emptyPortfolio: PortfolioSnapshot = {
      ...mockPortfolio,
      positions: [],
    };
    render(<PortfolioView portfolio={emptyPortfolio} />);

    expect(screen.getByText(/No active positions held/i)).toBeInTheDocument();
  });
});
