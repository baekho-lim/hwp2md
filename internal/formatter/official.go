// Package formatter 는 문서 변환 시 출력 서식 처리를 담당한다.
package formatter

import (
	"regexp"
	"strings"
)

// OfficialLevel 은 공문서 항목 기호의 계층 수준을 나타낸다.
// 행정업무의운영및혁신에관한규정시행규칙 별표 기준.
type OfficialLevel int

const (
	LevelNone OfficialLevel = 0
	Level1    OfficialLevel = 1 // 1. 2. 3. 또는 □
	Level2    OfficialLevel = 2 // 가. 나. 다. 또는 ○
	Level3    OfficialLevel = 3 // 1) 2) 3)
	Level4    OfficialLevel = 4 // 가) 나) 다)
	Level5    OfficialLevel = 5 // (1) (2) (3)
	Level6    OfficialLevel = 6 // (가) (나) (다)
	Level7    OfficialLevel = 7 // ① ② ③
)

// OfficialMarkerResult 는 항목 기호 감지 결과를 담는다.
type OfficialMarkerResult struct {
	Level   OfficialLevel
	Content string // 기호를 제외한 본문
}

// 한글 가나다 문자 목록 (행정업무규정 기준)
const koreanSyllables = "가나다라마바사아자차카타파하"

// 원문자 (① ~ ⑳)
const circledNumbers = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

// 패턴 정의: 순서 중요 — 더 구체적인 패턴(괄호 포함)을 먼저 검사
var officialPatterns = []struct {
	re    *regexp.Regexp
	level OfficialLevel
}{
	// Level 5: (1) (2) (3) — 괄호 + 아라비아 숫자
	{regexp.MustCompile(`^\((\d+)\)\s+(.+)$`), Level5},
	// Level 6: (가) (나) (다) — 괄호 + 한글
	{regexp.MustCompile(`^\([` + koreanSyllables + `]\)\s+(.+)$`), Level6},

	// Level 7: ①②③ — 원문자
	{regexp.MustCompile(`^[` + circledNumbers + `]\s*(.+)$`), Level7},

	// Level 1: □ 기호
	{regexp.MustCompile(`^□\s*(.+)$`), Level1},
	// Level 2: ○ 기호
	{regexp.MustCompile(`^○\s*(.+)$`), Level2},

	// Level 1: 1. 2. 3. — 아라비아 숫자 + 마침표
	{regexp.MustCompile(`^(\d+)\.\s+(.+)$`), Level1},
	// Level 2: 가. 나. 다. — 한글 + 마침표
	{regexp.MustCompile(`^[` + koreanSyllables + `]\.\s+(.+)$`), Level2},

	// Level 3: 1) 2) 3) — 아라비아 숫자 + 닫는 괄호
	{regexp.MustCompile(`^(\d+)\)\s+(.+)$`), Level3},
	// Level 4: 가) 나) 다) — 한글 + 닫는 괄호
	{regexp.MustCompile(`^[` + koreanSyllables + `]\)\s+(.+)$`), Level4},
}

// DetectOfficialMarker 는 텍스트가 공문서 항목 기호로 시작하는지 검사한다.
func DetectOfficialMarker(text string) OfficialMarkerResult {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		return OfficialMarkerResult{Level: LevelNone}
	}

	for _, p := range officialPatterns {
		matches := p.re.FindStringSubmatch(trimmed)
		if matches != nil {
			content := strings.TrimSpace(matches[len(matches)-1])
			return OfficialMarkerResult{
				Level:   p.level,
				Content: content,
			}
		}
	}

	return OfficialMarkerResult{Level: LevelNone}
}

// FormatOfficialMarker 는 감지된 항목 기호를 Markdown 형식으로 변환한다.
//   - Level 1 → "## 내용"
//   - Level 2 이상 → 깊이에 따른 탭(2칸 스페이스) + "- 내용"
func FormatOfficialMarker(result OfficialMarkerResult) string {
	if result.Level == LevelNone {
		return ""
	}

	if result.Level == Level1 {
		return "## " + result.Content
	}

	// Level 2 = 들여쓰기 없음, Level 3 = 2칸, Level 4 = 4칸, ...
	indent := strings.Repeat("  ", int(result.Level)-2)
	return indent + "- " + result.Content
}
