package formatter

import (
	"testing"
)

func TestDetectOfficialMarker(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		level   OfficialLevel
		content string
	}{
		// 감지 안 됨
		{"빈 문자열", "", LevelNone, ""},
		{"일반 텍스트", "일반 문장입니다.", LevelNone, ""},
		{"숫자로 시작하지만 마커 아님", "100명이 참여했다.", LevelNone, ""},

		// Level 1: □
		{"□ 기호", "□ 추진 배경", Level1, "추진 배경"},
		{"□ 기호 (앞뒤 공백)", "  □ 추진 배경  ", Level1, "추진 배경"},

		// Level 1: 아라비아 숫자 + 마침표
		{"숫자 마침표 1", "1. 원서 접수처 및 마감 일자", Level1, "원서 접수처 및 마감 일자"},
		{"숫자 마침표 2", "2. 채용 분야 및 인원", Level1, "채용 분야 및 인원"},
		{"숫자 마침표 10", "10. 기타 사항", Level1, "기타 사항"},

		// Level 2: ○
		{"○ 기호", "○ 부족한 인력 보충", Level2, "부족한 인력 보충"},

		// Level 2: 한글 + 마침표
		{"가 마침표", "가. 구청", Level2, "구청"},
		{"나 마침표", "나. 우편 접수", Level2, "우편 접수"},
		{"다 마침표", "다. 온라인 접수", Level2, "온라인 접수"},
		{"하 마침표", "하. 마지막 항목", Level2, "마지막 항목"},

		// Level 3: 숫자 + 닫는 괄호
		{"숫자 괄호 1", "1) 환경자원과", Level3, "환경자원과"},
		{"숫자 괄호 2", "2) 환경미화과", Level3, "환경미화과"},

		// Level 4: 한글 + 닫는 괄호
		{"가 괄호", "가) 정규직", Level4, "정규직"},
		{"나 괄호", "나) 계약직", Level4, "계약직"},

		// Level 5: (숫자)
		{"괄호 숫자 1", "(1) 서류 전형", Level5, "서류 전형"},
		{"괄호 숫자 2", "(2) 면접 전형", Level5, "면접 전형"},

		// Level 6: (한글)
		{"괄호 가", "(가) 행정 분야", Level6, "행정 분야"},
		{"괄호 나", "(나) 기술 분야", Level6, "기술 분야"},

		// Level 7: 원문자
		{"원문자 1", "① 이력서", Level7, "이력서"},
		{"원문자 2", "② 자기소개서", Level7, "자기소개서"},
		{"원문자 10", "⑩ 기타 서류", Level7, "기타 서류"},

		// 엣지 케이스: 마커 뒤에 공백 없이 바로 텍스트
		{"□ 공백 없음", "□추진 배경", Level1, "추진 배경"},
		{"○ 공백 없음", "○부족한 인력", Level2, "부족한 인력"},
		{"① 공백 없음", "①이력서", Level7, "이력서"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			result := DetectOfficialMarker(tc.input)
			if result.Level != tc.level {
				t.Errorf("Level: got %d, want %d", result.Level, tc.level)
			}
			if tc.level != LevelNone && result.Content != tc.content {
				t.Errorf("Content: got %q, want %q", result.Content, tc.content)
			}
		})
	}
}

func TestFormatOfficialMarker(t *testing.T) {
	tests := []struct {
		name     string
		result   OfficialMarkerResult
		expected string
	}{
		{
			"LevelNone",
			OfficialMarkerResult{Level: LevelNone},
			"",
		},
		{
			"Level1 → ## heading",
			OfficialMarkerResult{Level: Level1, Content: "추진 배경"},
			"## 추진 배경",
		},
		{
			"Level2 → - item",
			OfficialMarkerResult{Level: Level2, Content: "부족한 인력 보충"},
			"- 부족한 인력 보충",
		},
		{
			"Level3 → 2칸 들여쓰기 + - item",
			OfficialMarkerResult{Level: Level3, Content: "환경자원과"},
			"  - 환경자원과",
		},
		{
			"Level4 → 4칸 들여쓰기 + - item",
			OfficialMarkerResult{Level: Level4, Content: "정규직"},
			"    - 정규직",
		},
		{
			"Level5 → 6칸 들여쓰기 + - item",
			OfficialMarkerResult{Level: Level5, Content: "서류 전형"},
			"      - 서류 전형",
		},
		{
			"Level6 → 8칸 들여쓰기 + - item",
			OfficialMarkerResult{Level: Level6, Content: "행정 분야"},
			"        - 행정 분야",
		},
		{
			"Level7 → 10칸 들여쓰기 + - item",
			OfficialMarkerResult{Level: Level7, Content: "이력서"},
			"          - 이력서",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := FormatOfficialMarker(tc.result)
			if got != tc.expected {
				t.Errorf("got %q, want %q", got, tc.expected)
			}
		})
	}
}

func TestDetectAndFormat_IssueExample1(t *testing.T) {
	// 이슈 #22 예시 1: □ + ○ 조합
	inputs := []struct {
		text     string
		expected string
	}{
		{"□ 추진 배경", "## 추진 배경"},
		{"○ 부족한 인력 보충으로 업무 수행을 원활히 하고자 함", "- 부족한 인력 보충으로 업무 수행을 원활히 하고자 함"},
		{"○ 시민들에게 다양한 일자리를 제공하기 위함", "- 시민들에게 다양한 일자리를 제공하기 위함"},
	}

	for _, tc := range inputs {
		result := DetectOfficialMarker(tc.text)
		if result.Level == LevelNone {
			t.Errorf("마커 감지 실패: %q", tc.text)
			continue
		}
		got := FormatOfficialMarker(result)
		if got != tc.expected {
			t.Errorf("입력 %q → got %q, want %q", tc.text, got, tc.expected)
		}
	}
}

func TestDetectAndFormat_IssueExample2(t *testing.T) {
	// 이슈 #22 예시 2: 숫자 + 한글 가나다 + 숫자 괄호 조합
	inputs := []struct {
		text     string
		expected string
	}{
		{"1. 원서 접수처 및 마감 일자", "## 원서 접수처 및 마감 일자"},
		{"가. 구청", "- 구청"},
		{"1) 환경자원과", "  - 환경자원과"},
		{"2) 환경미화과", "  - 환경미화과"},
		{"나. 우편 접수", "- 우편 접수"},
		{"다. 온라인 접수", "- 온라인 접수"},
	}

	for _, tc := range inputs {
		result := DetectOfficialMarker(tc.text)
		if result.Level == LevelNone {
			t.Errorf("마커 감지 실패: %q", tc.text)
			continue
		}
		got := FormatOfficialMarker(result)
		if got != tc.expected {
			t.Errorf("입력 %q → got %q, want %q", tc.text, got, tc.expected)
		}
	}
}
