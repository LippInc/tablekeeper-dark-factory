// A reservation as the service returns it, read the same way on every screen.

// The booked tables, from the restaurant's detail. A stage-1 reservation names its one table
// as `table_id` alone.
export function reservedTables(restaurant, reservation) {
  return (reservation.table_ids ?? [reservation.table_id])
    .map((id) => restaurant.tables.find((table) => table.id === id));
}

// The local date of the booking, as YYYY-MM-DD.
export function dateOf(reservation) {
  return reservation.starts_at_local.slice(0, 10);
}
