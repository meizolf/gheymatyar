/** Typed DTOs matching backend Pydantic schemas. */

export interface SupplierInfo {
  key: string
  display_name: string
}

export type DetectionConfidence = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'

export interface DetectionInfo {
  detected_supplier_id: string | null
  detected_supplier_name: string | null
  confidence: DetectionConfidence | string
  evidence: string[]
  requires_confirmation: boolean
  text_extracted?: boolean
  ocr_used?: boolean
}

export interface DetectSupplierResponse {
  session_id: string
  pdf_filename: string | null
  supplier_confirmed: boolean
  detection: DetectionInfo
  summary: SessionSummary
}

export interface InvalidRow {
  row_number: number
  column: string | null
  reason: string
  code: string | null
  name: string | null
}

export interface SessionSummary {
  session_id: string
  supplier_key: string | null
  supplier_display_name: string | null
  supplier_confirmed?: boolean
  detection?: DetectionInfo | null
  pioneers_filename: string | null
  pdf_filename: string | null
  product_count: number
  invalid_row_count: number
  invalid_rows: InvalidRow[]
  duplicate_codes: Record<string, number[]>
  supplier_item_count: number
  matched_count: number
  unmatched_count: number
  ambiguous_count: number
  ignored_count?: number
  warning_count: number
  exportable_count: number
  parse_warnings: string[]
  export_available: boolean
}

export interface SessionCreateResponse {
  session_id: string
}

export type MatchStatus = 'MATCHED' | 'UNMATCHED' | 'AMBIGUOUS' | 'IGNORED'
export type ReviewDecision = 'INCLUDE' | 'EXCLUDE' | 'APPROVE'
export type MatchType = 'SAVED_MAPPING' | 'EXACT_NAME' | 'MANUAL'

export interface CandidateSuggestion {
  row_number?: number
  pioneers_code?: string | null
  pioneers_name?: string | null
  score?: number
  [key: string]: unknown
}

export interface Candidate {
  candidate_id: string
  row_number: number | null
  pioneers_code: string | null
  pioneers_name: string | null
  supplier_code: string | null
  supplier_name: string
  old_price: string | null
  new_price: string | null
  absolute_change: string | null
  percentage_change: string | null
  match_type: MatchType | string | null
  status: MatchStatus | string
  review_decision: ReviewDecision | string
  warnings: string[]
  pricing_blockers?: string[]
  source_currency?: string | null
  price_basis?: string | null
  tax_state?: string | null
  source_page?: number | null
  source_unit?: string | null
  suggestions: CandidateSuggestion[]
  exportable: boolean
  supplier_name_normalized: string | null
}

export interface CandidatesResponse {
  session_id: string
  matched_count: number
  unmatched_count: number
  ambiguous_count: number
  ignored_count?: number
  candidates: Candidate[]
}

export interface ProductSearchResult {
  row_number: number
  code?: string | null
  name?: string | null
  [key: string]: unknown
}

export interface ProductSearchResponse {
  results: ProductSearchResult[]
}

export interface ExportResponse {
  session_id: string
  /** `xls` is an Excel 97–2003 (BIFF8) workbook, the default download. */
  format: 'xls' | 'xlsx'
  output_filename: string
  updated_count: number
  exported_row_count: number
  content_sha256: string
  download_path: string
}

export interface ExcelDownload {
  blob: Blob
  exportedRowCount: number
  contentSha256: string
}

export interface SettingsResponse {
  settings: Record<string, string>
}

export interface Mapping {
  id: number
  supplier_key: string
  supplier_name_raw: string
  supplier_name_normalized: string
  pioneers_name_raw: string
  pioneers_name_normalized: string
  pioneers_code: string | null
  supplier_code?: string | null
  unit_normalized?: string | null
  legacy_unscoped?: boolean
  mapping_type: string
  created_at: string
  updated_at: string
}

export interface MappingsListResponse {
  supplier_key: string
  mappings: Mapping[]
}
