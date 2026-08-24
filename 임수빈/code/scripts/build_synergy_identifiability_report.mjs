import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const dataDir = path.join(root, "data", "processed");
const outputDir = path.join(root, "outputs", "promotion_synergy_validation");
await fs.mkdir(outputDir, { recursive: true });

async function loadCsv(file, sheetName) {
  const text = (await fs.readFile(path.join(dataDir, file), "utf8")).replace(/^\uFEFF/, "");
  const temp = await Workbook.fromCSV(text, { sheetName });
  const values = temp.worksheets.getItem(sheetName).getUsedRange(true).values;
  const headers = values[0].map(value => String(value).replace(/^\uFEFF/, ""));
  const rows = values.slice(1).map(row => row.map(value => {
    if (value === null || value === undefined || value === "") return null;
    if (String(value).toLowerCase() === "true") return true;
    if (String(value).toLowerCase() === "false") return false;
    if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(String(value))) return Number(value);
    return value;
  }));
  return [headers, ...rows];
}

const countValues = await loadCsv("promotion_group_counts.csv", "프로모션 구성");
const diagnosticValues = await loadCsv("promotion_synergy_identifiability.csv", "식별 가능성");
const workbook = Workbook.create();
const summary = workbook.worksheets.add("결론");
const counts = workbook.worksheets.add("프로모션 구성");
const diagnostic = workbook.worksheets.add("식별 가능성");
counts.getRangeByIndexes(0, 0, countValues.length, countValues[0].length).values = countValues;
diagnostic.getRangeByIndexes(0, 0, diagnosticValues.length, diagnosticValues[0].length).values = diagnosticValues;

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["결합 프로모션 시너지 검증 가능성 점검"]];
summary.getRange("A3:B9").values = [
  ["검증 질문", "결합 효과가 전단 효과와 진열 효과의 합보다 큰가?"],
  ["필요 계산", "결합 - 진열만 - 전단만 + 무프로모션"],
  ["무프로모션 행", null],
  ["현재 데이터로 검증 가능", null],
  ["판정 이유", "무프로모션 기준군이 없어 상품의 기본 판매수준을 제거할 수 없음"],
  ["현재 말할 수 있는 것", "결합 프로모션은 진열만 및 전단만 각각보다 판매성과가 높게 관찰됨"],
  ["다음 방법", "무프로모션 주차가 포함된 데이터 확보 또는 2×2 요인 실험"],
];
summary.getRange("B5").formulas = [["='프로모션 구성'!B2"]];
summary.getRange("B6").formulas = [["=IF(B5>0,\"가능성 있음\",\"불가능\")"]];
summary.getRange("A11:H11").merge();
summary.getRange("A11").values = [["프로모션 구성"]];
summary.getRange("A12:C16").values = countValues;
summary.getRange("C13:C16").format.numberFormat = "0.0%";
summary.getRange("A18:H20").merge();
summary.getRange("A18").values = [["해석: 현재 결과가 무의미한 것은 아니다. 결합 방식이 각 단독 방식보다 높은 성과를 보였다는 비교는 유효하다. 다만 이를 '1+1을 초과하는 시너지' 또는 '비용 대비 수익성'으로 확대 해석할 수는 없다."]];

const navy = "#17365D";
const blue = "#D9EAF7";
const yellow = "#FFF2CC";
for (const sheet of [summary, counts, diagnostic]) sheet.showGridLines = false;
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 } };
summary.getRange("A3:A9").format = { fill: blue, font: { bold: true } };
summary.getRange("B6").format = { fill: "#F4CCCC", font: { bold: true, color: "#990000" } };
summary.getRange("A11:H11").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A12:C12").format = { fill: blue, font: { bold: true } };
summary.getRange("A18:H20").format = { fill: yellow, font: { italic: true, color: "#7F6000" }, wrapText: true };
summary.getRange("A3:B9").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 72;
summary.getRange("C:C").format.columnWidth = 18;
summary.getRange("D:H").format.columnWidth = 5;
summary.freezePanes.freezeRows(1);

function styleSheet(sheet, values) {
  const rows = values.length;
  const cols = values[0].length;
  sheet.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.columnWidth = 24;
  sheet.getRangeByIndexes(0, 0, rows, cols).format.wrapText = true;
  sheet.freezePanes.freezeRows(1);
}
styleSheet(counts, countValues);
counts.getRange("C2:C5").format.numberFormat = "0.0%";
styleSheet(diagnostic, diagnosticValues);
diagnostic.getRange("A:H").format.columnWidth = 34;

const check = await workbook.inspect({ kind: "table", range: "결론!A1:C18", include: "values,formulas", tableMaxRows: 22, tableMaxCols: 5 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
for (const [sheetName, range, file] of [
  ["결론", "A1:H20", "synergy_identifiability_summary.png"],
  ["프로모션 구성", "A1:C5", "synergy_group_counts.png"],
  ["식별 가능성", "A1:H2", "synergy_identifiability_detail.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, file), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "promotion_synergy_identifiability_report.xlsx"));
