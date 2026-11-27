/** Shapes shared across modules. The server owns the real data; these mirror it. */

export interface ProductOption {
  label: string;
  price: number;
}

export interface Product {
  id: string;
  name: string;
  emoji: string;
  /** The one picture URL for this product ('' when there is none yet). */
  photo?: string;
  options: ProductOption[];
}

/** Cart entry keyed by "productId|optionIndex". */
export interface CartEntry {
  qty: number;
  note: string;
  product: Product;
  optionIndex: number;
}

export interface CartLine {
  key: string;
  product: Product;
  option: ProductOption;
  qty: number;
  note: string;
  unitPrice: number;
  subtotal: number;
}

export type PayMethod = "delivery" | "before";

/** A one-time Monnify transfer account, mirroring payments.public_view on the server. */
export interface MonnifyPayment {
  orderId: string;
  status: string;
  bank: string;
  bankCode?: string;
  accountName: string;
  accountNumber: string;
  amount: number;
  paymentReference: string;
  transactionReference: string;
  expiresOn: string;
  secondsLeft: number;
  amountPaid?: number | null;
  message: string;
}

export type PaymentDetail =
  | { type: "card"; last4: string }
  | { type: "transfer"; bank: string }
  | { type: "ussd"; bank: string; code: string }
  | Record<string, never>;

export interface OrderInfo {
  address: string;
  phone: string;
}

export interface PlacedOrder {
  id: string;
  total: number;
  address: string;
  city: string;
  phone: string;
  payMethod: PayMethod;
  paymentDetail: PaymentDetail;
  items: { qty: number; name: string }[];
}

export interface ApiError {
  error?: string;
}
