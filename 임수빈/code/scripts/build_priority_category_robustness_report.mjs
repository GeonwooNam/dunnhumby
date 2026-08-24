import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const dataDir = path.join(root, "data", "processed");
const outputDir = path.join(root, "outputs", "promotion_category_prioritization");
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

const summaryValues = await loadCsv("priority_category_robustness_summary.csv", "최종 판정");
const detailValues = await loadCsv("priority_category_robustness_tests.csv", "상세 검정");
const headers = summaryValues[0];
const idx = Object.fromEntries(headers.map((value, i) => [value, i]));
const rows = summaryValues.slice(1).sort((a, b) =>
  (a[idx.final_recommendation] === "최우선 적용" ? 0 : 1) - (b[idx.final_recommendation] === "최우선 적용" ? 0 : 1)
  || b[idx.passed_checks] - a[idx.passed_checks]
);

const workbook = Workbook.create();
const dashboard = workbook.worksheets.add("강건성 요약");
const decisions = workbook.worksheets.add("최종 판정");
const details = workbook.worksheets.add("상세 검정");
decisions.getRangeByIndexes(0, 0, summaryValues.length, summaryValues[0].length).values = summaryValues;
details.getRangeByIndexes(0, 0, detailValues.length, detailValues[0].length).values = detailValues;

dashboard.getRange("A1:H1").merge();
dashboard.getRange("A1").values = [["우선 적용 카테고리 강건성 검증"]];
dashboard.getRange("A3:B7").values = [
  ["검증 대상", "기존 우선 적용 카테고리 7개"],
  ["검증 조건", "±1·±2·±4주 × 진열만·전단만 비교 = 카테고리당 6개 조건"],
  ["최우선 적용", null],
  ["파일럿", null],
  ["우선순위 하향", null],
];
dashboard.getRange("B5").formulas = [["=COUNTIF('최종 판정'!$M$2:$M$8,\"최우선 적용\")"]];
dashboard.getRange("B6").formulas = [["=COUNTIF('최종 판정'!$M$2:$M$8,\"파일럿\")"]];
dashboard.getRange("B7").formulas = [["=COUNTIF('최종 판정'!$M$2:$M$8,\"우선순위 하향\")"]];
dashboard.getRange("A9:H9").merge();
dashboard.getRange("A9").values = [["최종 카테고리 판정"]];
dashboard.getRange("A10:H10").values = [["DEPARTMENT", "COMMODITY_DESC", "통과 조건", "전체 조건", "최소 판매발생률 효과", "최소 매출 효과", "최종 판정", "해석"]];
dashboard.getRangeByIndexes(10, 0, rows.length, 8).values = rows.map(row => [
  row[idx.DEPARTMENT], row[idx.COMMODITY_DESC], row[idx.passed_checks], row[idx.checks],
  row[idx.min_sales_effect], row[idx.min_revenue_effect], row[idx.final_recommendation], row[idx.recommendation_reason],
]);
dashboard.getRange("A20:H20").merge();
dashboard.getRange("A20").values = [["판정 기준"]];
dashboard.getRange("A21:B23").values = [
  ["최우선 적용", "6개 조건 모두에서 판매발생률·매출의 95% 신뢰구간 하한이 0 초과"],
  ["파일럿", "6개 조건의 평균 효과는 모두 양수지만 일부 신뢰구간이 0을 포함"],
  ["우선순위 하향", "일부 조건에서 판매발생률 또는 매출 평균 효과가 0 이하"],
];
dashboard.getRange("A25:H27").merge();
dashboard.getRange("A25").values = [["해석: 최우선 적용은 비용 검토 후 가장 먼저 파일럿할 대상이다. 관찰자료이므로 즉시 전면 적용이나 순수 인과효과를 의미하지 않는다."]];

const navy = "#17365D";
const lightBlue = "#D9EAF7";
const green = "#E2F0D9";
const yellow = "#FFF2CC";
for (const sheet of [dashboard, decisions, details]) sheet.showGridLines = false;
dashboard.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, verticalAlignment: "center" };
dashboard.getRange("A1:H1").format.rowHeight = 32;
dashboard.getRange("A3:A7").format = { fill: lightBlue, font: { bold: true } };
dashboard.getRange("B5:B6").format = { fill: green, font: { bold: true, color: "#274E13" } };
dashboard.getRange("A9:H9").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
dashboard.getRange("A10:H10").format = { fill: lightBlue, font: { bold: true }, wrapText: true };
dashboard.getRange("E11:E17").format.numberFormat = "0.000%";
dashboard.getRange("F11:F17").format.numberFormat = "0.0000";
dashboard.getRange("A20:H20").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
dashboard.getRange("A21:A23").format = { fill: lightBlue, font: { bold: true } };
dashboard.getRange("A25:H27").format = { fill: yellow, font: { italic: true, color: "#7F6000" }, wrapText: true, verticalAlignment: "top" };
dashboard.getRange("A3:H23").format.wrapText = true;
dashboard.getRange("A:A").format.columnWidth = 18;
dashboard.getRange("B:B").format.columnWidth = 34;
dashboard.getRange("C:G").format.columnWidth = 18;
dashboard.getRange("H:H").format.columnWidth = 58;
dashboard.getRange("G11:G17").conditionalFormats.add("containsText", { text: "최우선 적용", format: { fill: green, font: { bold: true, color: "#274E13" } } });
dashboard.getRange("G11:G17").conditionalFormats.add("containsText", { text: "파일럿", format: { fill: yellow, font: { color: "#7F6000" } } });
dashboard.freezePanes.freezeRows(1);

function styleSheet(sheet, values, widths = {}) {
  const rowCount = values.length;
  const colCount = values[0].length;
  sheet.getRangeByIndexes(0, 0, 1, colCount).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).format.columnWidth = 16;
  for (const [range, width] of Object.entries(widths)) sheet.getRange(range).format.columnWidth = width;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
}
styleSheet(decisions, summaryValues, { "A:A": 18, "B:B": 34, "M:M": 18, "N:N": 58 });
styleSheet(details, detailValues, { "A:A": 18, "B:B": 34, "D:D": 24 });
details.getRange(`G2:I${detailValues.length}`).format.numberFormat = "0.000%";
details.getRange(`K2:M${detailValues.length}`).format.numberFormat = "0.0000";

const check = await workbook.inspect({ kind: "table", range: "강건성 요약!A1:H25", include: "values,formulas", tableMaxRows: 30, tableMaxCols: 9 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);

for (const [sheetName, range, file] of [
  ["강건성 요약", "A1:H27", "priority_category_robustness_summary.png"],
  ["최종 판정", "A1:M8", "priority_category_robustness_decisions.png"],
  ["상세 검정", "A1:S16", "priority_category_robustness_details.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 0.9, format: "png" });
  await fs.writeFile(path.join(outputDir, file), new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "priority_category_robustness_report.xlsx"));
