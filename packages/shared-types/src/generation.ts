export interface GenerateRequest {
  type: 'micro_icon' | 'keyframe_scene' | 'route_sketch' | 'full_day_map';
  event_name?: string;
  activity_category?: string;
  location_name?: string;
  style?: {
    preset?: string;
    palette?: string[];
    line_style?: string;
    texture?: string;
    art_reference?: string;
  };
  approach?: string;
  prompt_override?: string;
  width?: number;
  height?: number;
  params?: Record<string, unknown>;
}

export interface GenerateResponse {
  image_url?: string;
  error?: string;
  format?: string;
  approach?: string;
  model?: string;
  prompt?: string;
  generation_time_ms?: number;
}

export interface ImageryResult {
  title: string;
  thumbnail_url: string;
  source: string;
  distance_meters?: number;
}
