// 계약: packages/contracts/openapi.yaml 의 `Me`.
//
// ⚠️ 표시 이름과 이메일은 없습니다. 계약이 두지 않기로 한 것이지 아직 안 넣은 것이 아닙니다 -
// 이메일을 두는 순간 개인정보 보관 항목이 하나 늡니다. 화면에 필요하다고 여기에 필드를
// 먼저 추가하면 그때부터 계약이 아니라 구두 합의입니다.
export interface Me {
  userId: string;
  loginId: string;
  createdAt: string;
}
