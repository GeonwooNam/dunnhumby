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
  const textColumns = new Set(["PRODUCT_ID", "CURR_SIZE_OF_PRODUCT"]);
  const rows = values.slice(1).map(row => row.map((value, col) => {
    if (value === null || value === undefined || value === "") return null;
    if (textColumns.has(headers[col])) return String(value);
    if (String(value).toLowerCase() === "true") return true;
    if (String(value).toLowerCase() === "false") return false;
    if (/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/.test(String(value))) return Number(value);
    return value;
  }));
  return [headers, ...rows];
}

const priorityValues = await loadCsv("promotion_category_priority.csv", "상세 통계");
const directionValues = await loadCsv("promotion_category_direction_candidates.csv", "방향성 후보");
const productValues = await loadCsv("promotion_priority_products.csv", "우선 상품");
const priorityHeader = priorityValues[0];
const priorityRows = priorityValues.slice(1);
const index = Object.fromEntries(priorityHeader.map((name, i) => [name, i]));
const groupOrder = { "우선 적용": 1, "안정적 적용 후보": 2, "추가 실험 필요": 3, "결합 근거 부족": 4, "비교 자료 부족": 5 };
const sortedRows = [...priorityRows].sort((a, b) =>
  (groupOrder[a[index.strategy_group]] ?? 9) - (groupOrder[b[index.strategy_group]] ?? 9)
  || (Number(b[index.priority_score]) || -1) - (Number(a[index.priority_score]) || -1)
);
const decisionHeader = ["DEPARTMENT", "COMMODITY_DESC", "전략 등급", "보수적 판매발생률 효과", "보수적 매출 효과", "최소 매칭 수", "종합 점수", "판정 이유"];
const decisionValues = [decisionHeader, ...sortedRows.map(row => [
  row[index.DEPARTMENT], row[index.COMMODITY_DESC], row[index.strategy_group],
  row[index.conservative_sales_effect], row[index.conservative_revenue_effect],
  row[index.coverage_matched_pairs], row[index.priority_score], row[index.strategy_reason],
])];
const topRows = sortedRows.filter(row => row[index.strategy_group] === "우선 적용");

const workbook = Workbook.create();
const summary = workbook.worksheets.add("최종 요약");
const decisions = workbook.worksheets.add("카테고리 판정");
const details = workbook.worksheets.add("상세 통계");
const directions = workbook.worksheets.add("방향성 후보");
const products = workbook.worksheets.add("우선 상품");

decisions.getRangeByIndexes(0, 0, decisionValues.length, decisionValues[0].length).values = decisionValues;
details.getRangeByIndexes(0, 0, priorityValues.length, priorityValues[0].length).values = priorityValues;
directions.getRangeByIndexes(0, 0, directionValues.length, directionValues[0].length).values = directionValues;
products.getRangeByIndexes(0, 0, productValues.length, productValues[0].length).values = productValues;

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["결합 프로모션 카테고리 우선순위"]];
summary.getRange("A3:B9").values = [
  ["분석 목적", "전단+진열을 모든 상품에 적용하지 않고, 추가 판매효과가 크고 안정적인 카테고리를 선별"],
  ["방향성 후보", null],
  ["신뢰도 통과", null],
  ["우선 적용", null],
  ["안정적 적용 후보", null],
  ["추가 실험 필요", null],
  ["핵심 결론", "결합 효과가 큰 카테고리는 육가공·간식·음료 중심이며, 해당 카테고리에 프로모션 자원을 우선 배분하는 전략이 타당"],
];
summary.getRange("B4").formulas = [["=COUNTIF('카테고리 판정'!$C$2:$C$253,\"우선 적용\")+COUNTIF('카테고리 판정'!$C$2:$C$253,\"안정적 적용 후보\")+COUNTIF('카테고리 판정'!$C$2:$C$253,\"추가 실험 필요\")"]];
summary.getRange("B5").formulas = [["=COUNTIF('카테고리 판정'!$C$2:$C$253,\"우선 적용\")+COUNTIF('카테고리 판정'!$C$2:$C$253,\"안정적 적용 후보\")"]];
summary.getRange("B6").formulas = [["=COUNTIF('카테고리 판정'!$C$2:$C$253,\"우선 적용\")"]];
summary.getRange("B7").formulas = [["=COUNTIF('카테고리 판정'!$C$2:$C$253,\"안정적 적용 후보\")"]];
summary.getRange("B8").formulas = [["=COUNTIF('카테고리 판정'!$C$2:$C$253,\"추가 실험 필요\")"]];

summary.getRange("A11:H11").merge();
summary.getRange("A11").values = [["우선 적용 카테고리 7개"]];
summary.getRange("A12:F12").values = [["DEPARTMENT", "COMMODITY_DESC", "보수적 판매발생률 효과", "보수적 매출 효과", "최소 매칭 수", "종합 점수"]];
summary.getRangeByIndexes(12, 0, topRows.length, 6).values = topRows.map(row => [
  row[index.DEPARTMENT], row[index.COMMODITY_DESC], row[index.conservative_sales_effect],
  row[index.conservative_revenue_effect], row[index.coverage_matched_pairs], row[index.priority_score],
]);
summary.getRange("A22:H22").merge();
summary.getRange("A22").values = [["선정 기준"]];
summary.getRange("A23:B28").values = [
  ["2단계 방향성", "결합−진열만과 결합−전단만에서 판매발생률·매출 평균이 모두 양수"],
  ["최소 상품 수", "각 비교에서 20개 이상"],
  ["최소 매칭 수", "각 비교에서 200건 이상"],
  ["신뢰도", "각 비교의 판매발생률·매출 95% 신뢰구간 하한이 모두 0 초과"],
  ["보수적 효과", "두 비교 효과 중 작은 값을 사용"],
  ["우선순위 점수", "보수적 판매발생률 40% + 보수적 매출 40% + 적용 규모 20%"],
];
summary.getRange("A30:H32").merge();
summary.getRange("A30").values = [["주의: 현재 데이터에는 프로모션 비용이 없으므로 수익성을 직접 확정할 수 없다. '우선 적용'은 비용 투입 전 파일럿 또는 예산 우선 검토 대상으로 해석한다."]];

const navy = "#17365D";
const lightBlue = "#D9EAF7";
const green = "#E2F0D9";
const yellow = "#FFF2CC";
for (const sheet of [summary, decisions, details, directions, products]) sheet.showGridLines = false;
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, verticalAlignment: "center" };
summary.getRange("A1:H1").format.rowHeight = 32;
summary.getRange("A3:A9").format = { fill: lightBlue, font: { bold: true } };
summary.getRange("B6:B7").format = { fill: green, font: { bold: true, color: "#274E13" } };
summary.getRange("A11:H11").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A12:F12").format = { fill: lightBlue, font: { bold: true } };
summary.getRange("C13:C19").format.numberFormat = "0.000%";
summary.getRange("D13:D19").format.numberFormat = "0.0000";
summary.getRange("E13:E19").format.numberFormat = "#,##0";
summary.getRange("F13:F19").format.numberFormat = "0.000";
summary.getRange("A22:H22").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A23:A28").format = { fill: lightBlue, font: { bold: true } };
summary.getRange("A30:H32").format = { fill: yellow, font: { italic: true, color: "#7F6000" }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A3:B28").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 58;
summary.getRange("C:F").format.columnWidth = 20;
summary.getRange("G:H").format.columnWidth = 4;
summary.freezePanes.freezeRows(1);

function styleSheet(sheet, values, widths = {}) {
  const rows = values.length;
  const cols = values[0].length;
  sheet.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.columnWidth = 16;
  for (const [range, width] of Object.entries(widths)) sheet.getRange(range).format.columnWidth = width;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
}
styleSheet(decisions, decisionValues, { "A:A": 18, "B:B": 32, "C:C": 18, "H:H": 55 });
decisions.getRange(`D2:D${decisionValues.length}`).format.numberFormat = "0.000%";
decisions.getRange(`E2:E${decisionValues.length}`).format.numberFormat = "0.0000";
decisions.getRange(`F2:F${decisionValues.length}`).format.numberFormat = "#,##0";
decisions.getRange(`G2:G${decisionValues.length}`).format.numberFormat = "0.000";
decisions.getRange(`C2:C${decisionValues.length}`).conditionalFormats.add("containsText", { text: "우선 적용", format: { fill: "#D9EAD3", font: { bold: true, color: "#274E13" } } });
decisions.getRange(`C2:C${decisionValues.length}`).conditionalFormats.add("containsText", { text: "추가 실험", format: { fill: "#FFF2CC", font: { color: "#7F6000" } } });
decisions.getRange(`C2:C${decisionValues.length}`).conditionalFormats.add("containsText", { text: "근거 부족", format: { fill: "#F4CCCC", font: { color: "#990000" } } });
decisions.tables.add(`A1:H${decisionValues.length}`, true, "CategoryDecisionTable");

styleSheet(details, priorityValues, { "A:A": 18, "B:B": 32, "AJ:AJ": 18, "AK:AK": 55 });
styleSheet(directions, directionValues, { "A:A": 18, "B:B": 32 });
styleSheet(products, productValues, { "A:A": 14, "B:B": 18, "C:C": 14, "D:E": 34, "F:F": 18 });
products.getRange(`S2:T${productValues.length}`).format.numberFormat = "0.0000";
products.getRange(`V2:W${productValues.length}`).format.numberFormat = "0.000";

const check = await workbook.inspect({ kind: "table", range: "최종 요약!A1:F30", include: "values,formulas", tableMaxRows: 35, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);

for (const [sheetName, range, file] of [
  ["최종 요약", "A1:H32", "promotion_category_priority_summary.png"],
  ["카테고리 판정", "A1:H18", "promotion_category_decisions.png"],
  ["상세 통계", "A1:K12", "promotion_category_details.png"],
  ["방향성 후보", "A1:J12", "promotion_category_direction.png"],
  ["우선 상품", "A1:W12", "promotion_priority_products.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 0.9, format: "png" });
  await fs.writeFile(path.join(outputDir, file), new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "promotion_category_priority_report.xlsx"));
