from typing import Optional, Dict, Any, List
from .schemas import Level1Bill


def compute_derived_metrics(bill: Level1Bill) -> Dict[str, Any]:
    """
    Computes deterministic metrics and verification values from extracted bill data.
    Provides verifiable numbers to assist Level 2 question answering.
    """
    metrics: Dict[str, Any] = {}

    # Calculate sum of line item charges
    sum_charges = sum(item.amount for item in bill.charges) if bill.charges else 0.0
    metrics["sum_charges"] = round(sum_charges, 2)

    # Calculate sum of line item taxes
    sum_taxes = sum(item.amount for item in bill.taxes) if bill.taxes else 0.0
    metrics["sum_taxes"] = round(sum_taxes, 2)

    # Subtotals comparison
    effective_taxes = bill.total_taxes if bill.total_taxes is not None else sum_taxes
    effective_charges = bill.total_charges if bill.total_charges is not None else sum_charges
    metrics["effective_taxes"] = round(effective_taxes, 2)
    metrics["effective_charges"] = round(effective_charges, 2)

    # Percentages of current bill
    if bill.current_bill and bill.current_bill > 0:
        if effective_taxes is not None:
            tax_pct = (effective_taxes / bill.current_bill) * 100.0
            metrics["tax_percentage_of_current_bill"] = round(tax_pct, 2)
        if effective_charges is not None:
            charges_pct = (effective_charges / bill.current_bill) * 100.0
            metrics["charges_percentage_of_current_bill"] = round(charges_pct, 2)

    # Average cost per unit (effective rate)
    if bill.units_consumed and bill.units_consumed > 0:
        if bill.current_bill is not None:
            metrics["effective_cost_per_unit_pkr"] = round(bill.current_bill / bill.units_consumed, 2)
        if effective_charges is not None:
            metrics["energy_cost_per_unit_pkr"] = round(effective_charges / bill.units_consumed, 2)

    # Meter reading difference
    if bill.current_reading is not None and bill.previous_reading is not None:
        metrics["meter_difference"] = bill.current_reading - bill.previous_reading

    # Late payment surcharge difference & percentage
    if (
        bill.payable_after_due_date is not None
        and bill.payable_within_due_date is not None
        and bill.payable_within_due_date > 0
    ):
        surcharge = bill.payable_after_due_date - bill.payable_within_due_date
        metrics["late_payment_difference"] = round(surcharge, 2)
        surcharge_pct = (surcharge / bill.payable_within_due_date) * 100.0
        metrics["late_payment_surcharge_percentage"] = round(surcharge_pct, 2)

    # Subsidies
    subsidy_items = [item for item in bill.charges if item.type == "subsidy"]
    if subsidy_items:
        total_subsidy = sum(abs(item.amount) for item in subsidy_items)
        metrics["total_subsidy_pkr"] = round(total_subsidy, 2)

    return metrics


def format_metrics_summary(bill: Level1Bill, metrics: Dict[str, Any]) -> str:
    """Formats verified calculations into an evidence block for Level 2 answering."""
    lines = ["--- Extracted & Deterministically Calculated Metrics (Code Ground Truth) ---"]
    if bill.provider:
        lines.append(f"- Provider: {bill.provider}")
    if bill.tariff:
        lines.append(f"- Tariff Code: {bill.tariff}")
    if bill.sanctioned_load_kw is not None:
        lines.append(f"- Sanctioned Load: {bill.sanctioned_load_kw} kW")
    if bill.bill_month:
        lines.append(f"- Billing Month: {bill.bill_month}")
    if bill.units_consumed is not None:
        lines.append(f"- Units Consumed / Billed: {bill.units_consumed} kWh")
    if "meter_difference" in metrics:
        lines.append(
            f"- Meter Difference: {metrics['meter_difference']} units "
            f"(Current Reading: {bill.current_reading}, Previous Reading: {bill.previous_reading})"
        )
    if bill.current_bill is not None:
        lines.append(f"- Current Bill Amount: PKR {bill.current_bill}")
    if "tax_percentage_of_current_bill" in metrics:
        lines.append(
            f"- Total Taxes: PKR {metrics['effective_taxes']} "
            f"({metrics['tax_percentage_of_current_bill']}% of current bill)"
        )
    if "charges_percentage_of_current_bill" in metrics:
        lines.append(
            f"- Total Electricity Charges: PKR {metrics['effective_charges']} "
            f"({metrics['charges_percentage_of_current_bill']}% of current bill)"
        )
    if "effective_cost_per_unit_pkr" in metrics:
        lines.append(f"- Effective Cost per Unit: PKR {metrics['effective_cost_per_unit_pkr']}/kWh")
    if "total_subsidy_pkr" in metrics:
        lines.append(f"- Government Subsidy / Relief: PKR {metrics['total_subsidy_pkr']}")
    if bill.arrears is not None:
        status = "Credit / Advance" if bill.arrears < 0 else "Outstanding arrears"
        lines.append(f"- Arrears: PKR {bill.arrears} ({status})")
    if bill.payable_within_due_date is not None:
        lines.append(f"- Payable Within Due Date: PKR {bill.payable_within_due_date} (Due: {bill.due_date})")
    if bill.payable_after_due_date is not None:
        diff_str = (
            f" (+PKR {metrics['late_payment_difference']} / {metrics.get('late_payment_surcharge_percentage')}%)"
            if "late_payment_difference" in metrics
            else ""
        )
        lines.append(f"- Payable After Due Date: PKR {bill.payable_after_due_date}{diff_str}")

    # Charge item details
    if bill.charges:
        lines.append("- Itemized Charges:")
        for c in bill.charges:
            lines.append(f"    * {c.type}: PKR {c.amount}")

    # Tax item details
    if bill.taxes:
        lines.append("- Itemized Taxes:")
        for t in bill.taxes:
            lines.append(f"    * {t.type}: PKR {t.amount}")

    return "\n".join(lines)
