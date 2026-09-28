import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { TradeLog } from './TradeLog';
import { TradeExecution } from '../types/dashboard';

const mockTrades: TradeExecution[] = [
  {
    fill_id: 'f-1',
    order_id: 'ord-1',
    symbol: 'BTC/USDT',
    side: 'buy',
    price: 50000.0,
    quantity: 0.5,
    commission: 12.5,
    timestamp_exchange: '2026-08-20T10:00:00Z',
    realized_pnl: 0.0,
  },
  {
    fill_id: 'f-2',
    order_id: 'ord-2',
    symbol: 'ETH/USDT',
    side: 'sell',
    price: 3000.0,
    quantity: 2.0,
    commission: 3.0,
    timestamp_exchange: '2026-08-20T10:05:00Z',
    realized_pnl: 250.0,
  },
];

describe('TradeLog Component', () => {
  it('renders execution rows with correct formatting', () => {
    render(<TradeLog trades={mockTrades} />);

    expect(screen.getByTestId('trade-row-f-1')).toBeInTheDocument();
    expect(screen.getByTestId('trade-row-f-2')).toBeInTheDocument();
    expect(screen.getByTestId('trade-pnl-f-2')).toHaveTextContent('+$250.00');
  });

  it('filters executions by side when button clicked', () => {
    render(<TradeLog trades={mockTrades} />);

    const buyBtn = screen.getByTestId('filter-buy');
    fireEvent.click(buyBtn);

    expect(screen.getByTestId('trade-row-f-1')).toBeInTheDocument();
    expect(screen.queryByTestId('trade-row-f-2')).not.toBeInTheDocument();
  });

  it('filters executions by search query', () => {
    render(<TradeLog trades={mockTrades} />);

    const searchInput = screen.getByTestId('trade-search-input');
    fireEvent.change(searchInput, { target: { value: 'ETH' } });

    expect(screen.queryByTestId('trade-row-f-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('trade-row-f-2')).toBeInTheDocument();
  });
});
