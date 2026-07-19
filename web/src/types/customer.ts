export interface CustomerOrderItem {
  name: string;
  qty: number;
  price: number;
  image_url?: string | null;
}

export interface CustomerOrder {
  id: number;
  order_sn: string;
  product_name: string;
  product_image?: string | null;
  total_amount: number;
  status: string;
  status_label: string;
  tracking_number?: string | null;
  shipping_address: string;
  created_at: string;
  items: CustomerOrderItem[];
}

export interface RefundRecord {
  id: number;
  after_sales_id: number;
  after_sales_status: string;
  after_sales_status_label: string;
  order_id: number;
  order_sn?: string | null;
  product_name: string;
  status: string;
  status_label: string;
  refund_amount: number;
  reason_detail: string;
  admin_note?: string | null;
  stage?: string | null;
  return_tracking_number?: string | null;
  timeline?: Array<{ label: string; note?: string; time: string }>;
  created_at: string;
  updated_at: string;
}


export interface AttachmentRecord {
  id: number;
  attachment_type: string;
  filename: string;
  content_type: string;
  url: string;
  order_sn?: string | null;
  refund_application_id?: number | null;
  created_at: string;
}

export interface NotificationRecord {
  id: number;
  after_sales_id?: number | null;
  after_sales_status?: string | null;
  after_sales_status_label?: string | null;
  title: string;
  content: string;
  target_type: string;
  target_id?: string | null;
  is_read: boolean;
  meta_data: Record<string, unknown>;
  created_at: string;
}
