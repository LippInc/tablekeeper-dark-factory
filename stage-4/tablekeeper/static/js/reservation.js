// A reservation as the service returns it, read the same way on every screen.

// The booked tables, from the restaurant's detail, each seating what the booking's accepted
// terms say, even when a newer policy says otherwise. A stage-1 reservation names its one table
// as `table_id` alone; an earlier stage's reservation has no terms and keeps the detail's.
export function reservedTables(restaurant, reservation) {
  const capacities = reservation.accepted_terms?.capacities ?? {};
  return (reservation.table_ids ?? [reservation.table_id])
    .map((id) => restaurant.tables.find((table) => table.id === id))
    .map((table) => ({ ...table, capacity: capacities[table.id] ?? table.capacity }));
}

// The local date of the booking, as YYYY-MM-DD.
export function dateOf(reservation) {
  return reservation.starts_at_local.slice(0, 10);
}
